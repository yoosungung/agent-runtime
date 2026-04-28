// Custom agent image — raw contract example (Go / net/http).
//
// Image contract:
//
//	POST /invoke  — AgentInvokeRequest body + x-principal, x-runtime-cfg headers
//	GET  /healthz — liveness
//	GET  /readyz  — readiness
package main

import (
	"encoding/base64"
	"encoding/json"
	"log"
	"net/http"
	"os"
)

var runtimePool = os.Getenv("RUNTIME_POOL")

type invokeRequest struct {
	Agent     string         `json:"agent"`
	Version   string         `json:"version"`
	Input     map[string]any `json:"input"`
	SessionID string         `json:"session_id"`
}

func healthz(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.Write([]byte(`{"status":"ok"}`))
}

func invoke(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var req invokeRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "invalid JSON body", http.StatusBadRequest)
		return
	}

	// Decode principal
	principal := map[string]any{}
	if h := r.Header.Get("X-Principal"); h != "" {
		b, _ := base64.StdEncoding.DecodeString(h)
		json.Unmarshal(b, &principal)
	}

	// Decode merged config
	cfg := map[string]any{}
	if h := r.Header.Get("X-Runtime-Cfg"); h != "" {
		b, _ := base64.StdEncoding.DecodeString(h)
		json.Unmarshal(b, &cfg)
	}

	// ── Your agent logic here ─────────────────────────────────────────────
	result := map[string]any{
		"output":    "Hello from " + runtimePool,
		"principal": principal["sub"],
		"cfg_keys":  keys(cfg),
	}
	// ──────────────────────────────────────────────────────────────────────

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]any{"result": result})
}

func keys(m map[string]any) []string {
	ks := make([]string, 0, len(m))
	for k := range m {
		ks = append(ks, k)
	}
	return ks
}

func main() {
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}
	http.HandleFunc("/healthz", healthz)
	http.HandleFunc("/readyz", healthz)
	http.HandleFunc("/invoke", invoke)
	log.Printf("listening on :%s pool=%s", port, runtimePool)
	log.Fatal(http.ListenAndServe(":"+port, nil))
}
