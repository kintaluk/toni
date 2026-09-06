"""
TONI - Google Cloud Run Deployment Utility
Automates pre-deployment test validation, environment audit, and gcloud execution.

Allows deploying the FastAPI service to Google Cloud Run effortlessly, either by
running the commands directly or generating a copy-pasteable script for dry-runs.
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path

# Ensure UTF-8 output on Windows terminals
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Color coding for terminal output
RESET = "\033[0m"
BOLD = "\033[1m"
GREEN = "\033[32m"
BLUE = "\033[34m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
RED = "\033[31m"
WHITE = "\033[37m"

# Absolute Paths
REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
DOTENV_PATH = REPO_ROOT / ".env"

def run_local_tests() -> bool:
    """Run local pytests to ensure everything is functional before deploying."""
    print(f"\n{BOLD}{CYAN}[1/4] Running local verification tests...{RESET}")
    # Always prefer sys.executable -m pytest to use the active virtual environment
    cmd = [sys.executable, "-m", "pytest"]
    
    try:
        res = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace")
        if res.returncode == 0:
            print(f"{GREEN}[OK] All tests passed successfully.{RESET}")
            return True
        else:
            print(f"{RED}[FAIL] Local verification tests failed!{RESET}")
            print(res.stdout)
            print(res.stderr)
            return False
    except Exception as e:
        print(f"{RED}[FAIL] Failed to run tests: {e}{RESET}")
        return False

def parse_env_secrets() -> dict:
    """Scan .env to identify keys that must be supplied to Cloud Run."""
    print(f"\n{BOLD}{CYAN}[2/4] Auditing environment variables...{RESET}")
    secrets = {}
    if not DOTENV_PATH.exists():
        print(f"{YELLOW}[!] No .env file found at root. Using empty defaults.{RESET}")
        return secrets
    
    with open(DOTENV_PATH, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip("'\"")
                if key in ["PARALLEL_API_KEY", "WATCHMODE_API_KEY", "TMDB_API_KEY"]:
                    if val:
                        secrets[key] = val
                        print(f"  [OK] Found secret config for {GREEN}{key}{RESET}")
    return secrets

def get_gcloud_config() -> dict:
    """Fetch active gcloud configuration to pre-fill deployment parameters."""
    config = {
        "project": os.environ.get("GCP_PROJECT_ID", ""),
        "account": os.environ.get("GCP_ACCOUNT_EMAIL", ""),
        "region": os.environ.get("GCP_REGION", "us-central1")
    }
    
    gcloud_bin = shutil.which("gcloud")
    if not gcloud_bin:
        return config
        
    try:
        # Get project
        proj_res = subprocess.run([gcloud_bin, "config", "get-value", "project"], capture_output=True, text=True)
        if proj_res.returncode == 0 and proj_res.stdout.strip():
            config["project"] = proj_res.stdout.strip()
            
        # Get account
        acc_res = subprocess.run([gcloud_bin, "config", "get-value", "account"], capture_output=True, text=True)
        if acc_res.returncode == 0 and acc_res.stdout.strip():
            config["account"] = acc_res.stdout.strip()
    except Exception:
        pass
        
    return config

def main():
    print(f"{BOLD}{CYAN}==================================================={RESET}")
    print(f"{BOLD}{CYAN}          TONI - Cloud Run Deployment Prep         {RESET}")
    print(f"{BOLD}{CYAN}==================================================={RESET}")
    
    # 1. Run Tests
    if not run_local_tests():
        sys.exit(1)
        
    # 2. Get Secrets
    secrets = parse_env_secrets()
    if not secrets:
        print(f"{RED}[!] Warning: No keys (PARALLEL_API_KEY) found in .env! Deployment might fail at runtime.{RESET}")
    
    # 3. Fetch Configuration
    print(f"\n{BOLD}{CYAN}[3/4] Initialising Google Cloud settings...{RESET}")
    gcloud_cfg = get_gcloud_config()
    print(f"  GCP Project:  {BLUE}{gcloud_cfg['project']}{RESET}")
    print(f"  GCP Account:  {BLUE}{gcloud_cfg['account']}{RESET}")
    
    service_name = "toni-app"
    region = gcloud_cfg["region"]
    project_id = gcloud_cfg["project"] if gcloud_cfg["project"] else "GCP_PROJECT_ID"
    
    # Environment variables (do not include reserved PORT variable or secrets here)
    env_vars_list = [
        "GOOGLE_GENAI_USE_VERTEXAI=True"
    ]
    env_vars_arg = ",".join(env_vars_list)
    
    # Secrets mapped via Cloud Run Secret Manager integration
    secrets_arg = ""
    if secrets:
        secrets_list = [f"{k}={k}:latest" for k in secrets.keys()]
        secrets_arg = ",".join(secrets_list)
    
    # Define Artifact Registry path (replaces deprecated gcr.io)
    image_tag = f"{region}-docker.pkg.dev/{project_id}/toni-repo/{service_name}:latest"
    
    # Build Deploy Command list
    build_cmd = f"gcloud builds submit --tag {image_tag} ."
    
    deploy_cmd_parts = [
        f"gcloud run deploy {service_name}",
        f"  --image {image_tag}",
        "  --platform managed",
        f"  --region {region}",
        "  --allow-unauthenticated",
        f"  --set-env-vars=\"{env_vars_arg}\""
    ]
    if secrets_arg:
        deploy_cmd_parts.append(f"  --set-secrets=\"{secrets_arg}\"")
        
    deploy_cmd = " \\\n".join(deploy_cmd_parts)
    
    print(f"\n{BOLD}{CYAN}[4/4] Generation completed!{RESET}")
    print(f"To deploy TONI to Google Cloud Run, execute the following commands in your CLI:\n")
    
    print(f"{BOLD}{YELLOW}# 1. Build and push container using Google Cloud Build:{RESET}")
    print(f"{GREEN}{build_cmd}{RESET}\n")
    
    print(f"{BOLD}{YELLOW}# 2. Deploy container to Google Cloud Run:{RESET}")
    print(f"{GREEN}{deploy_cmd}{RESET}\n")
    
    print(f"{BOLD}{CYAN}==================================================={RESET}")
    print(f"{BOLD}{WHITE}Dry-run notes:{RESET}")
    print(f" - Running Cloud Build compiles the Docker container directly in the cloud via Artifact Registry.")
    print(f" - Artifact Registry ({region}-docker.pkg.dev) is utilized as gcr.io is deprecated.")
    print(f" - Deploying to Cloud Run automatically exposes port 8080 and configures HTTPS endpoints.")
    print(f" - Environment secrets (e.g., Parallel and Watchmode keys) are mapped using Google Cloud Secret Manager.")
    print(f"{BOLD}{CYAN}==================================================={RESET}")

if __name__ == "__main__":
    main()
