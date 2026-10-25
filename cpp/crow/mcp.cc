#include <crow.h>

#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <optional>
#include <string>
#include <utility>

namespace {

std::string env_or(const char* name, const char* fallback) {
  const char* value = std::getenv(name);
  return value && *value ? value : fallback;
}

std::optional<std::string> string_field(const crow::json::rvalue& object,
                                        const char* key) {
  if (object.t() != crow::json::type::Object || !object.has(key) ||
      object[key].t() != crow::json::type::String) {
    return std::nullopt;
  }
  return object[key].s();
}

std::optional<double> number_field(const crow::json::rvalue& object,
                                   const char* key) {
  if (object.t() != crow::json::type::Object || !object.has(key) ||
      object[key].t() != crow::json::type::Number) {
    return std::nullopt;
  }
  double value = std::strtod(
      static_cast<std::string>(object[key]).c_str(), nullptr);
  return std::isfinite(value) ? std::optional<double>(value) : std::nullopt;
}

crow::json::wvalue envelope(const crow::json::wvalue& id) {
  crow::json::wvalue message;
  message["jsonrpc"] = "2.0";
  message["id"] = crow::json::wvalue(id);
  return message;
}

crow::response reply(const crow::json::wvalue& id,
                     crow::json::wvalue result) {
  crow::json::wvalue message = envelope(id);
  message["result"] = std::move(result);
  return crow::response(message);
}

crow::response fail(const crow::json::wvalue& id, int code, const char* text,
                    int status = 200) {
  crow::json::wvalue message = envelope(id);
  message["error"]["code"] = code;
  message["error"]["message"] = text;
  return crow::response(status, message);
}

crow::json::wvalue tool_result(const std::string& text, bool is_error) {
  crow::json::wvalue content;
  content["type"] = "text";
  content["text"] = text;
  crow::json::wvalue result;
  result["content"] = crow::json::wvalue::list{content};
  result["isError"] = is_error;
  return result;
}

crow::json::wvalue initialize_result(const crow::json::rvalue& message) {
  std::string version = "2025-06-18";
  if (message.has("params")) {
    if (auto requested = string_field(message["params"], "protocolVersion")) {
      version = *requested;
    }
  }
  crow::json::wvalue result;
  result["protocolVersion"] = version;
  result["capabilities"]["tools"] = crow::json::wvalue::empty_object();
  result["serverInfo"]["name"] = "mcp-crow";
  result["serverInfo"]["version"] = "0.1.0";
  return result;
}

crow::json::wvalue tools_list_result() {
  crow::json::wvalue::list tools;
  for (const auto& [name, description] : {
           std::pair{"add", "Add a and b."},
           std::pair{"subtract", "Subtract b from a."},
           std::pair{"multiply", "Multiply a by b."},
           std::pair{"divide", "Divide a by b."}}) {
    crow::json::wvalue tool;
    tool["name"] = name;
    tool["description"] = description;
    tool["inputSchema"]["type"] = "object";
    tool["inputSchema"]["properties"]["a"]["type"] = "number";
    tool["inputSchema"]["properties"]["b"]["type"] = "number";
    tool["inputSchema"]["required"] = crow::json::wvalue::list{"a", "b"};
    tools.push_back(std::move(tool));
  }
  crow::json::wvalue result;
  result["tools"] = std::move(tools);
  return result;
}

crow::response call_tool(const crow::json::wvalue& id,
                         const crow::json::rvalue& message) {
  if (!message.has("params") ||
      message["params"].t() != crow::json::type::Object) {
    return fail(id, -32602, "Invalid params");
  }
  const auto& params = message["params"];
  auto name = string_field(params, "name");
  if (!name || !params.has("arguments")) {
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
  return reply(id, tool_result(crow::json::wvalue(value).dump(), false));
}

crow::response handle(const std::string& body) {
  crow::json::rvalue message = crow::json::load(body);
  if (!message) {
    return fail(crow::json::wvalue(nullptr), -32700, "Parse error", 400);
  }
  if (message.t() != crow::json::type::Object) {
    return fail(crow::json::wvalue(nullptr), -32600, "Invalid Request", 400);
  }
  if (!message.has("id")) {
    return crow::response(202);
  }

  crow::json::wvalue id(message["id"]);
  auto method = string_field(message, "method");
  if (!method) {
    return fail(id, -32600, "Invalid Request");
  }
  if (*method == "initialize") {
    return reply(id, initialize_result(message));
  }
  if (*method == "ping") {
    return reply(id, crow::json::wvalue::empty_object());
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
  crow::SimpleApp app;

  CROW_ROUTE(app, "/mcp").methods(crow::HTTPMethod::POST)(
      [](const crow::request& request) { return handle(request.body); });

  app.bindaddr(env_or("MCP_BIND", "127.0.0.1"))
      .port(static_cast<std::uint16_t>(std::stoi(env_or("MCP_PORT", "8000"))))
      .multithreaded()
      .run();
}
