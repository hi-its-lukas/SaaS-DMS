# Sage Sync Agent Build Makefile

VERSION ?= 1.0.0
BUILD_TIME := $(shell date -u +"%Y-%m-%dT%H:%M:%SZ")
LDFLAGS := -ldflags "-X main.Version=$(VERSION) -X main.BuildTime=$(BUILD_TIME) -s -w"

.PHONY: all build build-windows clean test

all: build

build:
	go build $(LDFLAGS) -o sage-sync-agent ./cmd/agent

build-windows:
	GOOS=windows GOARCH=amd64 go build $(LDFLAGS) -o SageSyncAgent.exe ./cmd/agent

build-windows-32:
	GOOS=windows GOARCH=386 go build $(LDFLAGS) -o SageSyncAgent_x86.exe ./cmd/agent

clean:
	rm -f sage-sync-agent SageSyncAgent.exe SageSyncAgent_x86.exe

test:
	go test -v ./...

# Build for release (smaller binary)
release: clean
	GOOS=windows GOARCH=amd64 go build $(LDFLAGS) -o SageSyncAgent.exe ./cmd/agent
	@echo "Built SageSyncAgent.exe v$(VERSION)"
	@ls -lh SageSyncAgent.exe
