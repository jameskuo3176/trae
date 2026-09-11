# QoR Recorder - Windows JSON 上传体验
#
# 前置条件:
#   1. 安装 GNU Make（可使用 make 或 mingw32-make）
#   2. Windows PowerShell 5.1 可用
#   3. 在 Web 管理页创建具有 upload scope 的 API Key
#
# PowerShell 用法:
#   $env:QOR_API_KEY = "qor_xxxxxxxxxxxxxxxx"
#   make health
#   make upload PROJECT_ID=1
#
# 如果命令名是 mingw32-make:
#   mingw32-make upload PROJECT_ID=1

SHELL := cmd.exe
.SHELLFLAGS := /D /S /C

QOR_SERVER ?= http://127.0.0.1:5000
PROJECT_ID ?= 1
MODULE_NAME ?= windows_upload_demo
VERSION ?= windows_$(shell powershell.exe -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss")
JSON_FILE ?= upload-demo.json
QOR_API_KEY ?=
MARK_RELEASED ?= false

.DEFAULT_GOAL := help
.PHONY: help health check upload release

help:
	@echo QoR Recorder Windows JSON upload demo
	@echo.
	@echo   make health
	@echo   make upload PROJECT_ID=1
	@echo   make release PROJECT_ID=1
	@echo.
	@echo Before upload, set the API key in PowerShell:
	@echo   $$env:QOR_API_KEY = "qor_xxxxxxxxxxxxxxxx"
	@echo.
	@echo Current server:  $(QOR_SERVER)
	@echo Current project: $(PROJECT_ID)
	@echo Current module:  $(MODULE_NAME)

health:
	@powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$$ErrorActionPreference='Stop'; try { $$r=Invoke-RestMethod -Uri '$(QOR_SERVER)/health' -Method Get; $$r | ConvertTo-Json -Depth 10 } catch { Write-Error ('Health check failed: ' + $$_.Exception.Message); exit 1 }"

check:
	@powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "if ([string]::IsNullOrWhiteSpace('$(QOR_API_KEY)')) { Write-Error 'QOR_API_KEY is empty. Run: $$env:QOR_API_KEY = \"qor_xxx\"'; exit 1 }; if (-not (Test-Path -LiteralPath '$(JSON_FILE)')) { Write-Error 'JSON file not found: $(JSON_FILE)'; exit 1 }; Write-Host '[OK] Configuration is ready.'"

upload: check
	@powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$$ErrorActionPreference='Stop'; try { $$p=Get-Content -Raw -LiteralPath '$(JSON_FILE)' | ConvertFrom-Json; $$p.upload.project_id=[int]'$(PROJECT_ID)'; $$p.upload.module_name='$(MODULE_NAME)'; $$p.upload.version='regr_$(VERSION)'; $$p.upload.full_dir='/demo/windows/regr_$(VERSION)/main/$(MODULE_NAME)'; $$p.upload.release_dir=$$p.upload.full_dir; $$p.upload.mark_released=[System.Convert]::ToBoolean('$(MARK_RELEASED)'); $$p.records[0].module_name='$(MODULE_NAME)'; $$body=$$p | ConvertTo-Json -Depth 30; $$headers=@{'X-API-Key'='$(QOR_API_KEY)'}; $$r=Invoke-RestMethod -Uri '$(QOR_SERVER)/api/v1/qor/upload' -Method Post -Headers $$headers -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($$body)); Write-Host '[OK] Upload succeeded'; $$r | ConvertTo-Json -Depth 10 } catch { if ($$_.ErrorDetails.Message) { Write-Host $$_.ErrorDetails.Message }; Write-Error ('Upload failed: ' + $$_.Exception.Message); exit 1 }"

release:
	@$(MAKE) upload PROJECT_ID=$(PROJECT_ID) MODULE_NAME=$(MODULE_NAME) VERSION=$(VERSION) JSON_FILE=$(JSON_FILE) QOR_SERVER=$(QOR_SERVER) QOR_API_KEY=$(QOR_API_KEY) MARK_RELEASED=true
