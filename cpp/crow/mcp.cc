#include <crow.h>

#include <cstdint>
#include <cstdlib>
#include <optional>
#include <string>

namespace {

using crow::json::rvalue;
using crow::json::type;
using crow::json::wvalue;

std::string env_or(const char* name, const char* fallback) {
  const char* value = std::getenv(name);
  return value && *value ? value : fallback;
}

std::optional<std::string> string_field(const rvalue& object, const char* key) {
  if (object.t() != type::Object || !object.has(key) ||
      object[key].t() != type::String) {
    return std::nullopt;
  }
  return object[key].s();
}

wvalue envelope(const wvalue& id) {
  wvalue message;
  message["jsonrpc"] = "2.0";
  message["id"] = wvalue(id);
  return message;
}

crow::response reply(const wvalue& id, wvalue result) {
  wvalue message = envelope(id);
  message["result"] = std::move(result);
  return crow::response(message);
}

crow::response fail(const wvalue& id, int code, const char* text,
                    int status = 200) {
  wvalue message = envelope(id);
  message["error"]["code"] = code;
  message["error"]["message"] = text;
  return crow::response(status, message);
}

wvalue initialize_result(const rvalue& request) {
  std::string version = "2025-06-18";
  if (request.has("params")) {
    if (auto requested = string_field(request["params"], "protocolVersion")) {
      version = *requested;
    }
  }
  wvalue result;
  result["protocolVersion"] = version;
  result["capabilities"]["tools"] = wvalue::empty_object();
  result["serverInfo"]["name"] = "mcp-crow";
  result["serverInfo"]["version"] = "0.1.0";
  return result;
}

wvalue tools_list_result() {
  wvalue tool;
  tool["name"] = "echo";
  tool["description"] = "Dummy tool";
  tool["inputSchema"]["type"] = "object";
  tool["inputSchema"]["properties"]["text"]["type"] = "string";
  tool["inputSchema"]["required"] = wvalue::list{"text"};

  wvalue result;
  result["tools"] = wvalue::list{tool};
  return result;
}

crow::response handle(const std::string& body) {
  rvalue request = crow::json::load(body);
  if (!request || request.t() != type::Object) {
    return fail(wvalue(nullptr), -32700, "Parse error", 400);
  }
  if (!request.has("id")) {
    return crow::response(202);
  }

  wvalue id(request["id"]);
  auto method = string_field(request, "method");
  if (!method) {
    return fail(id, -32600, "Invalid Request");
  }
  if (*method == "initialize") {
    return reply(id, initialize_result(request));
  }
  if (*method == "ping") {
    return reply(id, wvalue::empty_object());
  }
  if (*method == "tools/list") {
    return reply(id, tools_list_result());
  }
  return fail(id, -32601, "Method not found");
}

}

int main() {
  crow::SimpleApp app;

  CROW_ROUTE(app, "/mcp").methods(crow::HTTPMethod::POST)(
      [](const crow::request& request) { return handle(request.body); });

  app.bindaddr(env_or("MCP_BIND", "127.0.0.1"))
      .port(static_cast<std::uint16_t>(std::stoi(env_or("MCP_PORT", "8080"))))
      .multithreaded()
      .run();
}
