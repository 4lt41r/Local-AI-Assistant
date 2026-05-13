"""
scripts/health_check.py — Verify all JARVIS services are running
Run after installer to confirm everything is working
"""

import sys
import asyncio
import httpx

BACKEND_URL = "http://localhost:8000"
OLLAMA_URL  = "http://localhost:11434"

CHECKS = {
    "Backend /health":       f"{BACKEND_URL}/health",
    "System stats":          f"{BACKEND_URL}/system/stats",
    "Ollama /api/tags":      f"{OLLAMA_URL}/api/tags",
}

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
RESET  = "\033[0m"


async def check(name: str, url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(url)
            ok = r.status_code == 200
            status = f"{GREEN}OK{RESET}" if ok else f"{RED}FAIL ({r.status_code}){RESET}"
            print(f"  {'✓' if ok else '✗'}  {name:<30} {status}")
            return ok
    except Exception as e:
        print(f"  ✗  {name:<30} {RED}UNREACHABLE — {e}{RESET}")
        return False


async def main():
    print(f"\n{YELLOW}  JARVIS Health Check{RESET}")
    print("  " + "─" * 44)
    results = []
    for name, url in CHECKS.items():
        results.append(await check(name, url))
    print("  " + "─" * 44)
    passed = sum(results)
    total  = len(results)
    color  = GREEN if passed == total else (YELLOW if passed > 0 else RED)
    print(f"  {color}{passed}/{total} checks passed{RESET}\n")
    return passed == total


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
