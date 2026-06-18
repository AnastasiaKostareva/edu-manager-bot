# Настраиваем кодировки сессии PowerShell для корректного ввода-вывода UTF-8
$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding = [System.Text.Encoding]::UTF8

# Получаем текущий Windows-путь (он гарантированно верный и с пробелами)
$WinPath = $PWD.Path

Write-Host "=== Запуск проекта ===" -ForegroundColor Cyan
Write-Host "Путь: $WinPath" -ForegroundColor Gray

# Используем флаг --cd для перехода в нужную папку силами самого WSL.
# Кавычки внутри bash -c больше не нужны для cd, передаем чистые команды.
wsl --cd "$WinPath" bash -c "docker compose up -d --build && docker compose logs --tail 20"

# ЕСЛИ У ВАС НЕ НАХОДИТСЯ ОБРАЗ ИЗ DOCKERFILE ПОПРОБУЙТЕ КИНУТЬ ПРОКСИ ДЛЯ WSL:
#  wsl -- bash -c "sudo mkdir -p /etc/docker && echo '{\"registry-mirrors\": [\"https://mirror.gcr.io\", \"https://dockerproxy.com\"]}' | sudo tee /etc/docker/daemon.json"

Read-Host "`nНажмите Enter для выхода"