"""
Identity Pack Smoke Test — Beta Stability Checklist
Run from backend/ directory: python smoke_test_identity_pack.py [options]

Flags:
  --mode dry|real          (default: dry)  dry = no API calls, no quota
  --max-characters N       (default: 1)    how many chars to test
  --timeout-seconds T      (default: 45)   per-request timeout for real mode

Examples:
  python smoke_test_identity_pack.py                        # dry, 1 char
  python smoke_test_identity_pack.py --mode dry --max-characters 8
  python smoke_test_identity_pack.py --mode real --max-characters 2 --timeout-seconds 360

Requires the dev server to be running on localhost:8000.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

BASE_URL = "http://127.0.0.1:8000"

# ── ANSI colour helpers ───────────────────────────────────────────────
_RST  = "\033[0m"
_GRN  = "\033[32m"
_YLW  = "\033[33m"
_RED  = "\033[31m"
_CYN  = "\033[36m"
_BLD  = "\033[1m"

def ok(s):   return f"{_GRN}✓{_RST} {s}"
def warn(s): return f"{_YLW}⚠{_RST} {s}"
def fail(s): return f"{_RED}✗{_RST} {s}"
def hdr(s):  return f"\n{_BLD}{_CYN}{s}{_RST}"

# ── Test character specs ──────────────────────────────────────────────

CHARACTERS = [
    {
        "label": "C1 · Human woman · realistic · (wardrobe ignored)",
        "char":  {"name": "Elena Vasquez", "species": "human"},
        "spec":  {
            "style": "realistic",
            "gender": "female",
            "age_band": "26-35",
            "identity": {"hair_color": "dark brown", "hair_length": "shoulder",
                         "eye_color": "green", "skin_tone": "tan"},
        },
    },
    {
        "label": "C2 · Human man · realistic",
        "char":  {"name": "Marcus Thorne", "species": "human"},
        "spec":  {
            "style": "realistic",
            "gender": "male",
            "age_band": "26-35",
            "identity": {"hair_color": "blonde", "hair_length": "short",
                         "eye_color": "blue", "skin_tone": "fair",
                         "face_features": ["square jaw", "stubble"]},
        },
    },
    {
        "label": "C3 · Fantasy elf · realistic",
        "char":  {"name": "Sylara", "species": "elf"},
        "spec":  {
            "style": "realistic",
            "gender": "female",
            "age_band": "18-25",
            "identity": {"hair_color": "silver", "hair_length": "long",
                         "eye_color": "violet", "skin_tone": "pale"},
            "build": {"body_type": "slender", "height_band": "tall"},
        },
    },
    {
        "label": "C4 · Anime style",
        "char":  {"name": "Hana Kira", "species": "human"},
        "spec":  {
            "style": "anime",
            "gender": "female",
            "age_band": "18-25",
            "identity": {"hair_color": "pink", "hair_length": "long",
                         "eye_color": "amber"},
        },
    },
    {
        "label": "C5 · Human woman · no optional fields",
        "char":  {"name": "Sofia Reyes", "species": "human"},
        "spec":  {
            "style": "realistic",
            "gender": "female",
            "age_band": "36-50",
            "identity": {"hair_color": "auburn", "hair_length": "wavy long",
                         "eye_color": "hazel", "skin_tone": "medium"},
        },
    },
    {
        "label": "C6 · Human man · illustration",
        "char":  {"name": "Dev Anand", "species": "human"},
        "spec":  {
            "style": "illustration",
            "gender": "male",
            "age_band": "36-50",
            "identity": {"hair_color": "black", "hair_length": "medium",
                         "eye_color": "dark brown", "skin_tone": "warm brown"},
            "marks_accessories": {"items": ["rectangular glasses"]},
        },
    },
    {
        "label": "C7 · Sci-fi android · realistic",
        "char":  {"name": "Vex-9", "species": "android"},
        "spec":  {
            "style": "realistic",
            "gender": "other",
            "age_band": "26-35",
            "identity": {"hair_color": "white", "hair_length": "short",
                         "eye_color": "electric blue", "skin_tone": "pale grey"},
            "extra_notes": "clean minimalist aesthetic, subtle geometric patterns",
        },
    },
    {
        "label": "C8 · Human woman · comic",
        "char":  {"name": "Rosa Vega", "species": "human"},
        "spec":  {
            "style": "comic",
            "gender": "female",
            "age_band": "26-35",
            "identity": {"hair_color": "fiery red", "hair_length": "short pixie",
                         "eye_color": "brown", "skin_tone": "light"},
            "marks_accessories": {"items": ["silver chain necklace"]},
        },
    },
]

# ── HTTP helper ───────────────────────────────────────────────────────

def _req(
    method: str,
    path: str,
    body: dict | None = None,
    token: str | None = None,
    timeout: int = 45,
) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body else None
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        f"{BASE_URL}{path}", data=data, headers=headers, method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            body_err = json.loads(e.read())
        except Exception:
            body_err = {"raw": "<unreadable>"}
        return e.code, body_err
    except TimeoutError:
        return -1, {"error": f"request timed out after {timeout}s"}

# ── Auth helpers ──────────────────────────────────────────────────────

def _login(run_id: str) -> str:
    """Register a fresh smoke-test user and return their bearer token."""
    email    = f"smoke{run_id}@example.com"
    password = "Smoketest1pass"
    _req("POST", "/auth/register",
         {"email": email, "username": f"smoke{run_id}", "password": password})
    _, d = _req("POST", "/auth/login", {"email": email, "password": password})
    return d.get("access_token", "")

# ── Dry-run smoke ──────────────────────────────────────────────────────

@dataclass
class DryResult:
    label: str
    success: bool = False
    elapsed_s: float = 0.0
    seed_provider: str = ""
    angles_provider: str = ""
    prompt_lengths: dict[str, int] = field(default_factory=dict)  # role → len
    warnings: list[str] = field(default_factory=list)
    error: str = ""


def smoke_dry(token: str, char_def: dict, timeout: int) -> DryResult:
    r = DryResult(label=char_def["label"])

    # Create character
    s, c = _req("POST", "/characters/", char_def["char"], token, timeout=timeout)
    if s not in (200, 201):
        r.error = f"create_char HTTP {s}: {c.get('detail', '?')}"
        return r
    cid = c["id"]

    # Dry-run generate
    t0 = time.time()
    s, d = _req(
        "POST",
        f"/characters/{cid}/identity-pack/generate?dry_run=true",
        {"identity_spec": char_def["spec"]},
        token,
        timeout=timeout,
    )
    r.elapsed_s = round(time.time() - t0, 2)

    if s != 200:
        r.error = f"HTTP {s}: {d.get('detail', d)}"
        return r
    if not d.get("dry_run"):
        r.error = "Response missing dry_run=true flag"
        return r

    r.seed_provider   = d.get("seed_provider", "?")
    r.angles_provider = d.get("angles_provider", "?")
    pp = d.get("prompts_preview", {})

    # Validate prompts_preview structure
    expected_keys = {"front", "three_quarter", "torso", "full_body"}
    missing_keys  = expected_keys - set(pp)
    if missing_keys:
        r.warnings.append(f"prompts_preview missing keys: {sorted(missing_keys)}")

    for key, prompt in pp.items():
        r.prompt_lengths[key] = len(prompt)
        if key == "front" and "passport-style headshot" not in prompt.lower():
            r.warnings.append("front prompt missing 'passport-style headshot'")
        if "fully clothed" not in prompt.lower():
            r.warnings.append(f"{key}: missing PG-13 safety suffix")

    r.success = not r.error and not r.warnings
    return r


# ── Real-mode smoke ────────────────────────────────────────────────────

@dataclass
class RealResult:
    label: str
    success: bool = False
    http_status: int = 0
    elapsed_s: float = 0.0
    tier_used: str = ""
    blocked_roles: list[str] = field(default_factory=list)
    providers: dict[str, str] = field(default_factory=dict)
    n_images: int = 0
    accept_ok: bool = False
    warnings: list[str] = field(default_factory=list)
    error: str = ""


def smoke_real(token: str, char_def: dict, timeout: int) -> RealResult:
    r = RealResult(label=char_def["label"])

    s, c = _req("POST", "/characters/", char_def["char"], token, timeout=30)
    if s not in (200, 201):
        r.error = f"create_char HTTP {s}: {c.get('detail', '?')}"
        return r
    cid = c["id"]

    t0 = time.time()
    s, pack = _req(
        "POST",
        f"/characters/{cid}/identity-pack/generate",
        {"identity_spec": char_def["spec"]},
        token,
        timeout=timeout,
    )
    r.elapsed_s  = round(time.time() - t0, 1)
    r.http_status = s

    if s == -1:
        r.error = f"timed out after {timeout}s"
        return r
    if s == 400:
        r.error = f"HTTP 400 moderation: {pack.get('detail', '?')}"
        return r
    if s != 200:
        r.error = f"HTTP {s}: {pack.get('detail', '?')}"
        return r

    r.tier_used     = pack.get("tier_used", "?")
    r.blocked_roles = pack.get("blocked_roles", [])
    images          = pack.get("images", [])
    r.n_images      = len(images)

    for img in images:
        role = (img.get("metadata_json") or {}).get("pack_role", "?")
        r.providers[role] = img.get("provider", "?")

    expected_roles = {
        "anchor_front", "anchor_three_quarter", "anchor_torso", "anchor_full_body",
    }
    found_roles = {
        (img.get("metadata_json") or {}).get("pack_role", "?") for img in images
    }
    if r.n_images != 4:
        r.warnings.append(f"image_count={r.n_images} (expected 4)")
    if found_roles != expected_roles:
        r.warnings.append(f"wrong_roles found={sorted(found_roles)}")

    # Accept (DB integrity check — would fail 422 if orphan records present)
    pack_id   = pack.get("pack_id", "")
    acc_s, acc = _req(
        "POST",
        f"/characters/{cid}/identity-pack/accept",
        {"pack_id": pack_id},
        token,
        timeout=30,
    )
    if acc_s == 200:
        r.accept_ok = True
        if len(acc.get("anchors", [])) != 4:
            r.warnings.append(f"accept returned {len(acc.get('anchors',[]))} anchors")
    else:
        r.warnings.append(
            f"accept HTTP {acc_s}: {acc.get('detail', '?')} (possible orphan records)"
        )

    r.success = r.n_images == 4 and r.accept_ok and not r.warnings
    return r


# ── Formatting ────────────────────────────────────────────────────────

def _prov(p: str) -> str:
    c = {"openai": _GRN, "google": _CYN, "fal": _YLW, "stub": _RED}.get(p, _RST)
    return f"{c}{p}{_RST}"


def _tier(t: str) -> str:
    c = {"A": _GRN, "B": _YLW, "C": _RED, "stub": _YLW}.get(t, _RST)
    return f"{c}Tier {t}{_RST}"


# ── Main ──────────────────────────────────────────────────────────────

def main() -> int:
    import uuid
    parser = argparse.ArgumentParser(description="Identity pack smoke test")
    parser.add_argument("--mode",           choices=["dry", "real"], default="dry")
    parser.add_argument("--max-characters", type=int, default=1,
                        help="Number of characters to test (default 1)")
    parser.add_argument("--timeout-seconds", type=int, default=45,
                        help="Per-request timeout for real mode (default 45)")
    args = parser.parse_args()

    chars_to_test = CHARACTERS[:args.max_characters]
    run_id        = uuid.uuid4().hex[:8]

    print(hdr(f"Identity Pack Smoke Test — run={run_id}  mode={args.mode}"))
    print(f"  Backend   : {BASE_URL}")
    print(f"  Mode      : {args.mode}")
    print(f"  Characters: {len(chars_to_test)}")
    if args.mode == "real":
        print(f"  Timeout   : {args.timeout_seconds}s per request")

    token = _login(run_id)
    if not token:
        print(fail("Login failed — is the backend running on :8000?"))
        return 1

    # ── Dry mode ──────────────────────────────────────────────────────
    if args.mode == "dry":
        print(hdr("Dry-Run Plans"))
        results: list[DryResult] = []
        for i, char_def in enumerate(chars_to_test, 1):
            sys.stdout.write(f"  [{i:02d}/{len(chars_to_test)}] {char_def['label']}  ... ")
            sys.stdout.flush()
            r = smoke_dry(token, char_def, timeout=args.timeout_seconds)
            results.append(r)

            if r.success:
                print(ok(f"{r.elapsed_s}s"))
            elif r.error:
                print(fail(f"ERROR: {r.error}"))
            else:
                print(warn(f"WARNINGS ({r.elapsed_s}s)"))

            if r.success or not r.error:
                print(f"      seed={_prov(r.seed_provider)}  "
                      f"angles={_prov(r.angles_provider)}")
                lens = "  ".join(f"{k}={v}ch" for k, v in sorted(r.prompt_lengths.items()))
                print(f"      prompt_lengths: {lens}")
                if r.prompt_lengths.get("front"):
                    from_k = "front"
                    preview = r.prompt_lengths  # already printed lengths; show snippet below
                for w in r.warnings:
                    print(f"      {_YLW}WARN: {w}{_RST}")

        n_ok  = sum(1 for r in results if r.success)
        n_err = sum(1 for r in results if r.error)
        n_wrn = sum(1 for r in results if r.warnings and not r.error)
        print(hdr("Dry-Run Summary"))
        print(f"  {n_ok}/{len(results)} clean  |  {n_wrn} warnings  |  {n_err} errors")
        if n_ok == len(results):
            print(ok("All prompt plans compiled correctly. No quota consumed."))
        else:
            for r in results:
                if r.error:
                    print(fail(f"{r.label}: {r.error}"))
                elif r.warnings:
                    print(warn(f"{r.label}: {', '.join(r.warnings)}"))
        return 0 if n_ok == len(results) else 1

    # ── Real mode ─────────────────────────────────────────────────────
    print(hdr("Generating Real Packs"))
    real_results: list[RealResult] = []
    for i, char_def in enumerate(chars_to_test, 1):
        sys.stdout.write(f"  [{i:02d}/{len(chars_to_test)}] {char_def['label']}  ... ")
        sys.stdout.flush()
        r = smoke_real(token, char_def, timeout=args.timeout_seconds)
        real_results.append(r)

        if r.success:
            status_str = ok(f"{r.elapsed_s}s  {_tier(r.tier_used)}  accept=ok")
        elif r.http_status == 400:
            status_str = warn(f"HTTP 400 MODERATION ({r.elapsed_s}s)")
        elif r.error:
            status_str = fail(f"{r.error}")
        else:
            status_str = warn(f"WARNINGS ({r.elapsed_s}s)  {_tier(r.tier_used)}")
        print(status_str)

        if r.providers:
            slots = ["anchor_front", "anchor_three_quarter", "anchor_torso", "anchor_full_body"]
            short = ["front", "3/4", "torso", "full"]
            parts = [f"{s}={_prov(r.providers.get(role,'?'))}"
                     for s, role in zip(short, slots)]
            print(f"      {' | '.join(parts)}")
        if r.blocked_roles:
            print(f"      {_YLW}blocked={r.blocked_roles}{_RST}")
        for w in r.warnings:
            print(f"      {_YLW}WARN: {w}{_RST}")

        # Stop after first hard failure in real mode
        if r.error and r.http_status not in (400, 0):
            print(warn("Stopping after first hard failure (real mode)."))
            break

    n_ok  = sum(1 for r in real_results if r.success)
    n_mod = sum(1 for r in real_results if r.http_status == 400)
    n_err = sum(1 for r in real_results if r.error and r.http_status not in (400, 0))
    n_wrn = sum(1 for r in real_results if r.warnings and r.success is False
                and r.http_status not in (400,))

    elapsed_ok = [r.elapsed_s for r in real_results if r.success]
    avg_t      = round(sum(elapsed_ok) / len(elapsed_ok), 1) if elapsed_ok else 0

    tier_dist: dict[str, int] = {}
    prov_counts: dict[str, int] = {}
    for r in real_results:
        if r.tier_used:
            tier_dist[r.tier_used] = tier_dist.get(r.tier_used, 0) + 1
        for _, p in r.providers.items():
            prov_counts[p] = prov_counts.get(p, 0) + 1

    print(hdr("Real-Mode Summary"))
    print(f"  {n_ok}/{len(real_results)} success | {n_mod} mod-400 | {n_err} error | {n_wrn} warning")
    print(f"  Tier dist    : {dict(sorted(tier_dist.items()))}")
    print(f"  Avg time     : {avg_t}s")
    print(f"  Provider dist: {dict(sorted(prov_counts.items()))}")

    print(hdr("Verdict"))
    if n_ok == len(real_results):
        print(ok(f"ALL {len(real_results)} PACKS PASSED — stable for beta."))
    elif n_ok >= len(real_results) * 0.8:
        print(warn(f"{n_ok}/{len(real_results)} passed — investigate warnings."))
    else:
        print(fail(f"Only {n_ok}/{len(real_results)} passed — NOT STABLE."))
    print()
    return 0 if n_ok == len(real_results) else 1


if __name__ == "__main__":
    sys.exit(main())
