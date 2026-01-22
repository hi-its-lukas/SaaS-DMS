# DMS Sync Agent Build Makefile

VERSION ?= 1.0.0
BUILD_TIME := $(shell date -u +"%Y-%m-%dT%H:%M:%SZ")
LDFLAGS := -ldflags "-X main.Version=$(VERSION) -X main.BuildTime=$(BUILD_TIME) -s -w"

.PHONY: all build build-windows clean test

all: build

build:
        go build $(LDFLAGS) -o dms-sync-agent ./cmd/agent

build-windows:
        GOOS=windows GOARCH=amd64 go build $(LDFLAGS) -o DMSSyncAgent.exe ./cmd/agent

build-windows-32:
        GOOS=windows GOARCH=386 go build $(LDFLAGS) -o DMSSyncAgent_x86.exe ./cmd/agent

clean:
        rm -f dms-sync-agent DMSSyncAgent.exe DMSSyncAgent_x86.exe

test:
        go test -v ./...

# Build for release (smaller binary)
release: clean
        GOOS=windows GOARCH=amd64 go build $(LDFLAGS) -o DMSSyncAgent.exe ./cmd/agent
        @echo "Built DMSSyncAgent.exe v$(VERSION)"
        @ls -lh DMSSyncAgent.exe
