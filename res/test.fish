#!/usr/bin/env fish

set -l url 127.0.0.1:8080/mcp
set -q argv[1]; and set url $argv[1]

http --print=Bhb POST $url jsonrpc=2.0 id:=1 method=initialize params:='{"protocolVersion":"2025-06-18"}'
http --print=Bhb POST $url jsonrpc=2.0 method=notifications/initialized
http --print=Bhb POST $url jsonrpc=2.0 id:=2 method=ping
http --print=Bhb POST $url jsonrpc=2.0 id:=3 method=tools/list
http --print=Bhb POST $url jsonrpc=2.0 method=tools/list
http --print=Bhb POST $url jsonrpc=2.0 id:=4 method=foo/bar
http --print=Bhb POST $url Content-Type:application/json --raw '{not json'
http --print=Bhb GET $url
