package main

import (
	"encoding/json"
	"io"
	"log"
	"net"
	"net/http"
	"os"
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
	return map[string]any{
		"tools": []any{
			map[string]any{
				"name":        "echo",
				"description": "Dummy tool",
				"inputSchema": map[string]any{
					"type":       "object",
					"properties": map[string]any{"text": map[string]any{"type": "string"}},
					"required":   []string{"text"},
				},
			},
		},
	}
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
	default:
		fail(w, id, -32601, "Method not found", http.StatusOK)
	}
}

func main() {
	mux := http.NewServeMux()
	mux.HandleFunc("POST /mcp", handle)
	addr := net.JoinHostPort(envOr("MCP_BIND", "127.0.0.1"), envOr("MCP_PORT", "8080"))
	log.Fatal(http.ListenAndServe(addr, mux))
}
