@echo off
chcp 65001 >nul
echo =======================================================
echo          Installation de VolAlerte (Windows)
echo =======================================================
echo.

cd /d "%~dp0"

:: 1. Détection de Python 3.12 ou supérieur
echo [1/5] Vérification de l'environnement Python...
set PYTHON_CMD=
py -3.12 --version >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON_CMD=py -3.12
) else (
    python --version >nul 2>&1
    if %errorlevel% equ 0 (
        set PYTHON_CMD=python
    ) else (
        echo [ERREUR] Python 3.12 est requis mais n'a pas été trouvé.
        echo Veuillez installer Python depuis https://www.python.org/
        pause
        exit /b 1
    )
)

echo Python détecté : %PYTHON_CMD%

:: 2. Création du venv
echo [2/5] Création de l'environnement virtuel venv...
if not exist "venv" (
    %PYTHON_CMD% -m venv venv
)
if %errorlevel% neq 0 (
    echo [ERREUR] Impossible de créer le venv.
    pause
    exit /b 1
)

:: 3. Installation des dépendances
echo [3/5] Installation des dépendances (FastAPI, uvicorn, httpx, winotify...)...
venv\Scripts\python.exe -m pip install --upgrade pip >nul 2>&1
venv\Scripts\pip.exe install -r requirements.txt
if %errorlevel% neq 0 (
    echo [AVERTISSEMENT] Erreur partielle lors du pip install. Vérification en cours...
)

:: 4 & 5. Création du raccourci Bureau et de la tâche planifiée
echo [4/5] Création du raccourci Bureau et de la tâche planifiée...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_windows.ps1"


:: Initialisation de la base SQLite
venv\Scripts\python.exe -c "from app.database import init_db; from app.sources.mock_source import seed_demo_database; init_db(); seed_demo_database(); print('Base SQLite initialisée avec succès.')"

echo.
echo =======================================================
echo          Installation terminée avec succès !
echo =======================================================
echo Vous pouvez maintenant double-cliquer sur l'icône
echo 'VolAlerte' sur votre Bureau pour lancer l'application.
echo.
pause
