package main

import (
	"encoding/json"
	"io"
	"log"
	"math"
	"net"
	"net/http"
	"os"
	"strconv"
)

func envOr(name, fallback string) string {
	if value := os.Getenv(name); value != "" {
		return value
	}
	return fallback
}

func stringField(object map[string]json.RawMessage, key string) (string, bool) {
	raw := object[key]
	if len(raw) == 0 || raw[0] != '"' {
		return "", false
	}
	var value string
	if err := json.Unmarshal(raw, &value); err != nil {
		return "", false
	}
	return value, true
}

func numberField(object map[string]json.RawMessage, key string) (float64, bool) {
	var value *float64
	if err := json.Unmarshal(object[key], &value); err != nil || value == nil {
		return 0, false
	}
	if math.IsNaN(*value) || math.IsInf(*value, 0) {
		return 0, false
	}
	return *value, true
}

func envelope(id json.RawMessage) map[string]any {
	return map[string]any{"jsonrpc": "2.0", "id": id}
}

func writeJSON(w http.ResponseWriter, status int, message map[string]any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(message); err != nil {
		log.Printf("write response: %v", err)
	}
}

func reply(w http.ResponseWriter, id json.RawMessage, result any) {
	message := envelope(id)
	message["result"] = result
	writeJSON(w, http.StatusOK, message)
}

func fail(w http.ResponseWriter, id json.RawMessage, code int, text string, status int) {
	message := envelope(id)
	message["error"] = map[string]any{"code": code, "message": text}
	writeJSON(w, status, message)
}

func toolResult(text string, isError bool) map[string]any {
	return map[string]any{
		"content": []any{map[string]any{"type": "text", "text": text}},
		"isError": isError,
	}
}

func initializeResult(message map[string]json.RawMessage) map[string]any {
	version := "2025-06-18"
	var params map[string]json.RawMessage
	if err := json.Unmarshal(message["params"], &params); err == nil {
		if requested, ok := stringField(params, "protocolVersion"); ok {
			version = requested
		}
	}
	return map[string]any{
		"protocolVersion": version,
		"capabilities":    map[string]any{"tools": map[string]any{}},
		"serverInfo":      map[string]any{"name": "mcp-bi", "version": "0.1.0"},
	}
}

func toolsListResult() map[string]any {
	tools := []any{}
	for _, definition := range [][2]string{
		{"add", "Add a and b."},
		{"subtract", "Subtract b from a."},
		{"multiply", "Multiply a by b."},
		{"divide", "Divide a by b."},
	} {
		tools = append(tools, map[string]any{
			"name":        definition[0],
			"description": definition[1],
			"inputSchema": map[string]any{
				"type": "object",
				"properties": map[string]any{
					"a": map[string]any{"type": "number"},
					"b": map[string]any{"type": "number"},
				},
				"required": []string{"a", "b"},
			},
		})
	}
	return map[string]any{"tools": tools}
}

func callTool(w http.ResponseWriter, id json.RawMessage, message map[string]json.RawMessage) {
	var params map[string]json.RawMessage
	if err := json.Unmarshal(message["params"], &params); err != nil || params == nil {
		fail(w, id, -32602, "Invalid params", http.StatusOK)
		return
	}
	name, named := stringField(params, "name")
	var arguments map[string]json.RawMessage
	if err := json.Unmarshal(params["arguments"], &arguments); err != nil || arguments == nil {
		fail(w, id, -32602, "Invalid params", http.StatusOK)
		return
	}
	a, hasA := numberField(arguments, "a")
	b, hasB := numberField(arguments, "b")
	if !named || !hasA || !hasB {
		fail(w, id, -32602, "Invalid params", http.StatusOK)
		return
	}
	var value float64
	switch name {
	case "add":
		value = a + b
	case "subtract":
		value = a - b
	case "multiply":
		value = a * b
	case "divide":
		if b == 0 {
			reply(w, id, toolResult("Cannot divide by zero.", true))
			return
		}
		value = a / b
	default:
		fail(w, id, -32602, "Invalid params", http.StatusOK)
		return
	}
	if math.IsNaN(value) || math.IsInf(value, 0) {
		reply(w, id, toolResult("Result is not finite.", true))
		return
	}
	reply(w, id, toolResult(strconv.FormatFloat(value, 'g', -1, 64), false))
}

func handle(w http.ResponseWriter, r *http.Request) {
	body, err := io.ReadAll(r.Body)
	if err != nil || !json.Valid(body) {
		fail(w, nil, -32700, "Parse error", http.StatusBadRequest)
		return
	}
	var message map[string]json.RawMessage
	if err := json.Unmarshal(body, &message); err != nil || message == nil {
		fail(w, nil, -32600, "Invalid Request", http.StatusBadRequest)
		return
	}
	id, ok := message["id"]
	if !ok {
		w.WriteHeader(http.StatusAccepted)
		return
	}
	method, ok := stringField(message, "method")
	if !ok {
		fail(w, id, -32600, "Invalid Request", http.StatusOK)
		return
	}
	switch method {
	case "initialize":
		reply(w, id, initializeResult(message))
	case "ping":
		reply(w, id, map[string]any{})
	case "tools/list":
		reply(w, id, toolsListResult())
	case "tools/call":
		callTool(w, id, message)
	default:
		fail(w, id, -32601, "Method not found", http.StatusOK)
	}
}

func main() {
	mux := http.NewServeMux()
	mux.HandleFunc("POST /mcp", handle)
	addr := net.JoinHostPort(envOr("MCP_BIND", "127.0.0.1"), envOr("MCP_PORT", "8000"))
	log.Fatal(http.ListenAndServe(addr, mux))
}
