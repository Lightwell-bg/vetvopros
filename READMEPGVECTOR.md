# Установка pgvector для Windows PostgreSQL (только через PowerShell)

Инструкция полностью для **Windows PowerShell**.

Проверенные пути на вашем ПК:
- `D:\Program Files\PostgreSQL\18\bin\psql.exe`
- `D:\Program Files\PostgreSQL\18\bin\pg_config.exe`
- `D:\Program Files\PostgreSQL\18\share`
- `D:\Program Files\PostgreSQL\18\lib`

## 1) Откройте PowerShell

- Для сборки можно обычный PowerShell.
- Для шага установки файлов в `Program Files` нужен **PowerShell от имени администратора**.

## 2) Проверка PostgreSQL и путей

```powershell
& "D:\Program Files\PostgreSQL\18\bin\pg_config.exe" --version
& "D:\Program Files\PostgreSQL\18\bin\pg_config.exe" --sharedir
& "D:\Program Files\PostgreSQL\18\bin\pg_config.exe" --pkglibdir
```

## 3) Проверка, установлен ли уже pgvector

```powershell
Test-Path "D:\Program Files\PostgreSQL\18\share\extension\vector.control"
```

Если `False`, продолжаем.

## 4) Подготовка исходников pgvector

```powershell
Set-Location D:\
if (-not (Test-Path "D:\tmp")) { New-Item -ItemType Directory -Path "D:\tmp" | Out-Null }
Set-Location "D:\tmp"
if (Test-Path "D:\tmp\pgvector") { Remove-Item "D:\tmp\pgvector" -Recurse -Force }
git clone --branch v0.8.1 https://github.com/pgvector/pgvector.git
Set-Location "D:\tmp\pgvector"
```

## 5) Подключение Build Tools и сборка

> Если Build Tools не установлены, сначала установите:
> [Build Tools for Visual Studio 2022](https://visualstudio.microsoft.com/visual-cpp-build-tools/)
> и workload `Desktop development with C++`.

```powershell
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
if (-not (Test-Path $vswhere)) {
  throw "vswhere.exe не найден. Установите Visual Studio Build Tools 2022."}

$VSROOT = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $VSROOT) {
  throw "Не найдена установленная C++ toolchain. Добавьте workload 'Desktop development with C++'."
}

$env:PGROOT = "D:\Program Files\PostgreSQL\18"
$env:Path = "$env:PGROOT\bin;$env:Path"

cmd /c "`"$VSROOT\Common7\Tools\VsDevCmd.bat`" -arch=x64 && nmake /F Makefile.win"
```

## 6) Установка собранных файлов (PowerShell от администратора)

Откройте **новое окно PowerShell от имени администратора** и выполните:

```powershell
Set-Location "D:\tmp\pgvector"
$env:PGROOT = "D:\Program Files\PostgreSQL\18"
$env:Path = "$env:PGROOT\bin;$env:Path"

$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$VSROOT = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath

cmd /c "`"$VSROOT\Common7\Tools\VsDevCmd.bat`" -arch=x64 && nmake /F Makefile.win install"
```

Проверка:

```powershell
Test-Path "D:\Program Files\PostgreSQL\18\share\extension\vector.control"
```

Должно вернуть `True`.

## 7) Создание extension в базе

```powershell
$env:PGPASSWORD = "3153735"
& "D:\Program Files\PostgreSQL\18\bin\psql.exe" -h localhost -p 5432 -U postgres -d vetvopros -c "CREATE EXTENSION IF NOT EXISTS vector;"
& "D:\Program Files\PostgreSQL\18\bin\psql.exe" -h localhost -p 5432 -U postgres -d vetvopros -c "SELECT extname, extversion FROM pg_extension WHERE extname='vector';"
```

## 8) Запуск проекта из PowerShell

```powershell
Set-Location "D:\1PythonProjects\20260404VetVopros\vetvopros"
& ".\.venv\Scripts\python.exe" -m alembic upgrade head
& ".\.venv\Scripts\python.exe" "src\run_bot.py"
```

## Быстрая диагностика

- `vswhere.exe не найден` -> не установлены Visual Studio Build Tools 2022.
- `PGROOT is not set` -> перед `nmake` не задан `$env:PGROOT`.
- `Access is denied` на `nmake ... install` -> окно PowerShell не запущено от администратора.
- `CREATE EXTENSION vector` падает -> проверьте `vector.control` в `...\share\extension\`.
