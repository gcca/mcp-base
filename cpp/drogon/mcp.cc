#include <drogon/drogon.h>

#include <cctype>
#include <charconv>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <exception>
#include <functional>
#include <limits>
#include <optional>
#include <string>
#include <system_error>
#include <utility>

namespace {

std::string env_or(const char* name, const char* fallback) {
  const char* value = std::getenv(name);
  return value && *value ? value : fallback;
}

std::optional<std::string> string_field(const Json::Value& object,
                                        const char* key) {
  if (!object.isObject() || !object.isMember(key) ||
      !object[key].isString()) {
    return std::nullopt;
  }
  return object[key].asString();
}

std::optional<double> number_field(const Json::Value& object,
                                   const char* key) {
  if (!object.isObject() || !object.isMember(key)) {
    return std::nullopt;
  }
  const Json::Value& value = object[key];
  if (value.isBool() ||
      !(value.isInt() || value.isUInt() || value.isInt64() ||
        value.isUInt64() || value.isDouble())) {
    return std::nullopt;
  }
  double number = value.asDouble();
  if (!std::isfinite(number)) {
    return std::nullopt;
  }
  return number;
}

Json::Value envelope(const Json::Value& id) {
  Json::Value message(Json::objectValue);
  message["jsonrpc"] = "2.0";
  message["id"] = id;
  return message;
}

drogon::HttpResponsePtr reply(const Json::Value& id, Json::Value result) {
  Json::Value message = envelope(id);
  message["result"] = std::move(result);
  return drogon::HttpResponse::newHttpJsonResponse(std::move(message));
}

drogon::HttpResponsePtr fail(const Json::Value& id, int code,
                             const char* text, int status = 200) {
  Json::Value message = envelope(id);
  message["error"]["code"] = code;
  message["error"]["message"] = text;
  auto response =
      drogon::HttpResponse::newHttpJsonResponse(std::move(message));
  response->setStatusCode(static_cast<drogon::HttpStatusCode>(status));
  return response;
}

Json::Value tool_result(const std::string& text, bool is_error) {
  Json::Value content(Json::objectValue);
  content["type"] = "text";
  content["text"] = text;
  Json::Value result(Json::objectValue);
  result["content"] = Json::Value(Json::arrayValue);
  result["content"].append(std::move(content));
  result["isError"] = is_error;
  return result;
}

Json::Value initialize_result(const Json::Value& message) {
  std::string version = "2025-06-18";
  if (message.isMember("params")) {
    if (auto requested = string_field(message["params"], "protocolVersion")) {
      version = *requested;
    }
  }
  Json::Value result(Json::objectValue);
  result["protocolVersion"] = version;
  result["capabilities"]["tools"] = Json::Value(Json::objectValue);
  result["serverInfo"]["name"] = "mcp-drogon";
  result["serverInfo"]["version"] = "0.1.0";
  return result;
}

Json::Value tools_list_result() {
  Json::Value tools(Json::arrayValue);
  for (const auto& [name, description] : {
           std::pair{"add", "Add a and b."},
           std::pair{"subtract", "Subtract b from a."},
           std::pair{"multiply", "Multiply a by b."},
           std::pair{"divide", "Divide a by b."}}) {
    Json::Value tool(Json::objectValue);
    tool["name"] = name;
    tool["description"] = description;
    tool["inputSchema"]["type"] = "object";
    tool["inputSchema"]["properties"]["a"]["type"] = "number";
    tool["inputSchema"]["properties"]["b"]["type"] = "number";
    Json::Value required(Json::arrayValue);
    required.append("a");
    required.append("b");
    tool["inputSchema"]["required"] = std::move(required);
    tools.append(std::move(tool));
  }
  Json::Value result(Json::objectValue);
  result["tools"] = std::move(tools);
  return result;
}

drogon::HttpResponsePtr call_tool(const Json::Value& id,
                                  const Json::Value& message) {
  if (!message.isMember("params") || !message["params"].isObject()) {
    return fail(id, -32602, "Invalid params");
  }
  const Json::Value& params = message["params"];
  auto name = string_field(params, "name");
  if (!name || !params.isMember("arguments")) {
    return fail(id, -32602, "Invalid params");
  }
  auto a = number_field(params["arguments"], "a");
  auto b = number_field(params["arguments"], "b");
  if (!a || !b) {
    return fail(id, -32602, "Invalid params");
  }
  double value;
  if (*name == "add") {
    value = *a + *b;
  } else if (*name == "subtract") {
    value = *a - *b;
  } else if (*name == "multiply") {
    value = *a * *b;
  } else if (*name == "divide") {
    if (*b == 0) {
      return reply(id, tool_result("Cannot divide by zero.", true));
    }
    value = *a / *b;
  } else {
    return fail(id, -32602, "Invalid params");
  }
  if (!std::isfinite(value)) {
    return reply(id, tool_result("Result is not finite.", true));
  }
  return reply(id, tool_result(Json::valueToString(value), false));
}

struct Cursor {
  const char* cur;
  const char* end;
  int depth;
};

void skip(Cursor& in) {
  while (in.cur < in.end &&
         (*in.cur == ' ' || *in.cur == '\n' || *in.cur == '\r' ||
          *in.cur == '\t')) {
    ++in.cur;
  }
}

void append_utf8(std::string& text, unsigned code) {
  if (code <= 0x7F) {
    text.push_back(static_cast<char>(code));
  } else if (code <= 0x7FF) {
    text.push_back(static_cast<char>(0xC0 | (code >> 6)));
    text.push_back(static_cast<char>(0x80 | (code & 0x3F)));
  } else if (code <= 0xFFFF) {
    text.push_back(static_cast<char>(0xE0 | (code >> 12)));
    text.push_back(static_cast<char>(0x80 | ((code >> 6) & 0x3F)));
    text.push_back(static_cast<char>(0x80 | (code & 0x3F)));
  } else {
    text.push_back(static_cast<char>(0xF0 | (code >> 18)));
    text.push_back(static_cast<char>(0x80 | ((code >> 12) & 0x3F)));
    text.push_back(static_cast<char>(0x80 | ((code >> 6) & 0x3F)));
    text.push_back(static_cast<char>(0x80 | (code & 0x3F)));
  }
}

bool hex4(Cursor& in, unsigned& code) {
  if (in.end - in.cur < 4) {
    return false;
  }
  code = 0;
  for (int i = 0; i < 4; ++i) {
    unsigned char digit = static_cast<unsigned char>(*in.cur++);
    code <<= 4;
    if (digit >= '0' && digit <= '9') {
      code += digit - '0';
    } else if (digit >= 'a' && digit <= 'f') {
      code += digit - 'a' + 10;
    } else if (digit >= 'A' && digit <= 'F') {
      code += digit - 'A' + 10;
    } else {
      return false;
    }
  }
  return true;
}

bool parse_string(Cursor& in, std::string& text) {
  if (in.cur >= in.end || *in.cur != '"') {
    return false;
  }
  ++in.cur;
  text.clear();
  while (in.cur < in.end) {
    unsigned char ch = static_cast<unsigned char>(*in.cur++);
    if (ch == '"') {
      return true;
    }
    if (ch < 0x20) {
      return false;
    }
    if (ch != '\\') {
      text.push_back(static_cast<char>(ch));
      continue;
    }
    if (in.cur >= in.end) {
      return false;
    }
    char escaped = *in.cur++;
    if (escaped == '"' || escaped == '\\' || escaped == '/') {
      text.push_back(escaped);
    } else if (escaped == 'b') {
      text.push_back('\b');
    } else if (escaped == 'f') {
      text.push_back('\f');
    } else if (escaped == 'n') {
      text.push_back('\n');
    } else if (escaped == 'r') {
      text.push_back('\r');
    } else if (escaped == 't') {
      text.push_back('\t');
    } else if (escaped == 'u') {
      unsigned code = 0;
      if (!hex4(in, code)) {
        return false;
      }
      if (code >= 0xD800 && code <= 0xDBFF) {
        if (in.end - in.cur < 6 || in.cur[0] != '\\' || in.cur[1] != 'u') {
          return false;
        }
        in.cur += 2;
        unsigned low = 0;
        if (!hex4(in, low) || low < 0xDC00 || low > 0xDFFF) {
          return false;
        }
        code = 0x10000 + (((code - 0xD800) << 10) | (low - 0xDC00));
      } else if (code >= 0xDC00 && code <= 0xDFFF) {
        return false;
      }
      append_utf8(text, code);
    } else {
      return false;
    }
  }
  return false;
}

bool parse_number(Cursor& in, Json::Value& out) {
  const char* start = in.cur;
  if (in.cur < in.end && *in.cur == '-') {
    ++in.cur;
  }
  if (in.cur >= in.end ||
      !std::isdigit(static_cast<unsigned char>(*in.cur))) {
    return false;
  }
  if (*in.cur == '0') {
    ++in.cur;
  } else {
    while (in.cur < in.end &&
           std::isdigit(static_cast<unsigned char>(*in.cur))) {
      ++in.cur;
    }
  }
  bool real = false;
  if (in.cur < in.end && *in.cur == '.') {
    real = true;
    ++in.cur;
    const char* fraction = in.cur;
    while (in.cur < in.end &&
           std::isdigit(static_cast<unsigned char>(*in.cur))) {
      ++in.cur;
    }
    if (in.cur == fraction) {
      return false;
    }
  }
  if (in.cur < in.end && (*in.cur == 'e' || *in.cur == 'E')) {
    real = true;
    ++in.cur;
    if (in.cur < in.end && (*in.cur == '+' || *in.cur == '-')) {
      ++in.cur;
    }
    const char* exponent = in.cur;
    while (in.cur < in.end &&
           std::isdigit(static_cast<unsigned char>(*in.cur))) {
      ++in.cur;
    }
    if (in.cur == exponent) {
      return false;
    }
  }
  if (!real) {
    std::int64_t whole = 0;
    auto as_int = std::from_chars(start, in.cur, whole);
    if (as_int.ec == std::errc() && as_int.ptr == in.cur) {
      out = static_cast<Json::Int64>(whole);
      return true;
    }
  }
  double number = 0;
  auto as_real = std::from_chars(start, in.cur, number);
  if (as_real.ec == std::errc::result_out_of_range) {
    double sign = start[0] == '-' ? -1.0 : 1.0;
    out = std::copysign(std::numeric_limits<double>::infinity(), sign);
    return true;
  }
  if (as_real.ec != std::errc() || as_real.ptr != in.cur) {
    return false;
  }
  out = number;
  return true;
}

bool parse_value(Cursor& in, Json::Value& out);

bool parse_array(Cursor& in, Json::Value& out) {
  if (++in.depth > 1000) {
    return false;
  }
  ++in.cur;
  out = Json::Value(Json::arrayValue);
  skip(in);
  if (in.cur < in.end && *in.cur == ']') {
    ++in.cur;
    --in.depth;
    return true;
  }
  while (in.cur < in.end) {
    Json::Value item;
    if (!parse_value(in, item)) {
      return false;
    }
    out.append(std::move(item));
    skip(in);
    if (in.cur >= in.end) {
      return false;
    }
    if (*in.cur == ']') {
      ++in.cur;
      --in.depth;
      return true;
    }
    if (*in.cur != ',') {
      return false;
    }
    ++in.cur;
    skip(in);
  }
  return false;
}

bool parse_object(Cursor& in, Json::Value& out) {
  if (++in.depth > 1000) {
    return false;
  }
  ++in.cur;
  out = Json::Value(Json::objectValue);
  skip(in);
  if (in.cur < in.end && *in.cur == '}') {
    ++in.cur;
    --in.depth;
    return true;
  }
  while (in.cur < in.end) {
    std::string key;
    if (!parse_string(in, key)) {
      return false;
    }
    skip(in);
    if (in.cur >= in.end || *in.cur != ':') {
      return false;
    }
    ++in.cur;
    Json::Value item;
    if (!parse_value(in, item)) {
      return false;
    }
    out[key] = std::move(item);
    skip(in);
    if (in.cur >= in.end) {
      return false;
    }
    if (*in.cur == '}') {
      ++in.cur;
      --in.depth;
      return true;
    }
    if (*in.cur != ',') {
      return false;
    }
    ++in.cur;
    skip(in);
  }
  return false;
}

bool parse_value(Cursor& in, Json::Value& out) {
  skip(in);
  if (in.cur >= in.end) {
    return false;
  }
  char ch = *in.cur;
  if (ch == '{') {
    return parse_object(in, out);
  }
  if (ch == '[') {
    return parse_array(in, out);
  }
  if (ch == '"') {
    std::string text;
    if (!parse_string(in, text)) {
      return false;
    }
    out = text;
    return true;
  }
  if (ch == '-' || std::isdigit(static_cast<unsigned char>(ch))) {
    return parse_number(in, out);
  }
  if (in.end - in.cur >= 4 && in.cur[0] == 't' && in.cur[1] == 'r' &&
      in.cur[2] == 'u' && in.cur[3] == 'e') {
    in.cur += 4;
    out = true;
    return true;
  }
  if (in.end - in.cur >= 5 && in.cur[0] == 'f' && in.cur[1] == 'a' &&
      in.cur[2] == 'l' && in.cur[3] == 's' && in.cur[4] == 'e') {
    in.cur += 5;
    out = false;
    return true;
  }
  if (in.end - in.cur >= 4 && in.cur[0] == 'n' && in.cur[1] == 'u' &&
      in.cur[2] == 'l' && in.cur[3] == 'l') {
    in.cur += 4;
    out = Json::Value();
    return true;
  }
  return false;
}

std::optional<Json::Value> read_json(const std::string& body) {
  Cursor in{body.data(), body.data() + body.size(), 0};
  Json::Value message;
  if (!parse_value(in, message)) {
    return std::nullopt;
  }
  skip(in);
  if (in.cur != in.end) {
    return std::nullopt;
  }
  return message;
}

drogon::HttpResponsePtr handle(const std::string& body) {
  std::optional<Json::Value> parsed;
  try {
    parsed = read_json(body);
  } catch (const std::exception&) {
    return fail(Json::Value(), -32700, "Parse error", 400);
  }
  if (!parsed) {
    return fail(Json::Value(), -32700, "Parse error", 400);
  }
  Json::Value message = std::move(*parsed);
  if (!message.isObject()) {
    return fail(Json::Value(), -32600, "Invalid Request", 400);
  }
  if (!message.isMember("id")) {
    auto response = drogon::HttpResponse::newHttpResponse(
        drogon::k202Accepted, drogon::CT_NONE);
    response->setBody("");
    return response;
  }

  Json::Value id = message["id"];
  auto method = string_field(message, "method");
  if (!method) {
    return fail(id, -32600, "Invalid Request");
  }
  if (*method == "initialize") {
    return reply(id, initialize_result(message));
  }
  if (*method == "ping") {
    return reply(id, Json::Value(Json::objectValue));
  }
  if (*method == "tools/list") {
    return reply(id, tools_list_result());
  }
  if (*method == "tools/call") {
    return call_tool(id, message);
  }
  return fail(id, -32601, "Method not found");
}

}

int main() {
  drogon::app().setLogPath("");
  drogon::app().registerHandler(
      "/mcp",
      [](const drogon::HttpRequestPtr& request,
         std::function<void(const drogon::HttpResponsePtr&)>&& callback) {
        callback(handle(std::string(request->getBody())));
      },
      {drogon::Post});
  drogon::app().addListener(
      env_or("MCP_BIND", "127.0.0.1"),
      static_cast<std::uint16_t>(std::stoi(env_or("MCP_PORT", "8000"))));
  drogon::app().run();
}
