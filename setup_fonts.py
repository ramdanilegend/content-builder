#!/usr/bin/env python3
"""
setup_fonts.py — Install all 30+ professional video-editor fonts
================================================================
Run this ONCE on the machine where the content-builder backend is running
(not needed inside Docker — the Dockerfile handles it automatically).

Usage:
    python setup_fonts.py            # dry-run: show what will be installed
    python setup_fonts.py --install  # actually install (may need sudo on Linux)

On Debian / Ubuntu:
    sudo python setup_fonts.py --install

On macOS (with Homebrew):
    brew install --cask font-open-sans font-roboto font-lato ...
    (see https://github.com/Homebrew/homebrew-cask-fonts)
"""

import subprocess
import sys
import platform

# ── Debian / Ubuntu apt packages ─────────────────────────────────────────────
APT_PACKAGES = [
    # Sans-serif / Modern
    "fonts-open-sans",        # Open Sans
    "fonts-roboto-hinted",    # Roboto
    "fonts-lato",             # Lato
    "fonts-ubuntu",           # Ubuntu
    "fonts-cantarell",        # Cantarell
    "fonts-noto",             # Noto Sans / Serif / Mono
    # Condensed / Narrow
    "fonts-croscore",         # Arimo, Tinos, Cousine
    "fonts-crosextra-caladea",# Caladea (Cambria substitute)
    "fonts-crosextra-carlito",# Carlito (Calibri substitute)
    # Serif / Editorial
    "fonts-freefont-ttf",     # FreeSans, FreeSerif, FreeMono
    "fonts-ebgaramond",       # EB Garamond
    "fonts-vollkorn",         # Vollkorn
    "fonts-linux-libertine",  # Linux Libertine + Biolinum
    # Monospace / Techy
    "fonts-inconsolata",      # Inconsolata
    "fonts-hack",             # Hack
    # Decorative / Special
    "fonts-jura",             # Jura (sci-fi)
    "fonts-mplus",            # M+ (Japanese-influenced)
    "fonts-urw-base35",       # Nimbus Sans, Roman, Gothic, Bookman, Mono
]

FONT_NAMES = {
    # category → list of (font_family_name, description)
    "Sans-Serif / Modern": [
        ("Poppins",           "geometric, YouTube titles"),
        ("Open Sans",         "humanist, news & docs"),
        ("Roboto",            "Google standard, clean UI"),
        ("Lato",              "corporate, explainer videos"),
        ("Ubuntu",            "modern, strong title cards"),
        ("Cantarell",         "rounded, approachable"),
        ("Noto Sans",         "international coverage"),
        ("Nimbus Sans",       "Helvetica-style, broadcast"),
        ("DejaVu Sans",       "versatile, wide support"),
        ("Liberation Sans",   "Arial substitute"),
        ("Arimo",             "ultra-clean, Chrome OS"),
        ("Carlito",           "Calibri-style, webinars"),
        ("FreeSans",          "general purpose"),
    ],
    "Condensed / Impact Style": [
        ("DejaVu Sans Condensed",  "action titles, sports graphics"),
        ("Liberation Sans Narrow", "information-dense lower-thirds"),
        ("Nimbus Sans Narrow",     "Impact-style bold titles"),
    ],
    "Serif / Editorial / Cinematic": [
        ("Lora",              "documentary, cinematic titles"),
        ("DejaVu Serif",      "editorial content"),
        ("Liberation Serif",  "news, formal productions"),
        ("Tinos",             "Times New Roman, journalism"),
        ("Caladea",           "Cambria-style, elegant"),
        ("EB Garamond",       "film credits, classical"),
        ("Vollkorn",          "scholarly, cinematic"),
        ("Linux Libertine",   "art-house, literary films"),
        ("Nimbus Roman",      "formal broadcast"),
        ("FreeSerif",         "wide Unicode coverage"),
        ("URW Bookman",       "warm editorial serif"),
        ("URW Gothic",        "Avant Garde display"),
    ],
    "Monospace / Techy": [
        ("Inconsolata",       "programmer aesthetic"),
        ("Hack",              "hacker / cyber overlay"),
        ("DejaVu Mono",       "code lower-thirds"),
        ("Liberation Mono",   "terminal graphics"),
        ("FreeMono",          "typewriter style"),
        ("Nimbus Mono",       "clean typewriter"),
    ],
    "Decorative / Special": [
        ("Jura",              "sci-fi, gaming, futuristic"),
        ("M Plus",            "Japanese-influenced, unique"),
        ("Linux Biolinum",    "humanist display"),
    ],
}


def print_font_list():
    total = 0
    print("\n📋  Professional Video Editor Fonts — 34 families\n")
    print("=" * 60)
    for category, fonts in FONT_NAMES.items():
        print(f"\n  ▸ {category}")
        for name, desc in fonts:
            print(f"      {name:<26}  {desc}")
            total += 1
    print(f"\n  Total: {total} font families\n")
    print("=" * 60)


def install_linux():
    print("\n🐧  Detected Linux — installing via apt-get ...\n")
    cmd = ["apt-get", "install", "-y"] + APT_PACKAGES
    try:
        subprocess.run(["apt-get", "update"], check=True)
        subprocess.run(cmd, check=True)
        subprocess.run(["fc-cache", "-fv"], check=True)
        print("\n✅  All fonts installed successfully!")
    except subprocess.CalledProcessError as e:
        print(f"\n❌  apt-get failed: {e}")
        print("    Try: sudo python setup_fonts.py --install")
        sys.exit(1)


def install_macos():
    """
    Install fonts on macOS.

    NOTE: homebrew/cask-fonts was deprecated in 2024. All font casks are now
    in the main homebrew/cask repo — no tap needed. We install each cask
    individually so a single missing cask doesn't abort the whole run.
    """
    print("\n🍎  Detected macOS — installing via Homebrew (main cask repo) ...\n")

    # Each entry is (label, [cask_name, ...alternative_names])
    # The installer tries each alternative in order, stopping at the first that works.
    # Notes:
    #   • font-dejavu     → includes DejaVu Sans, Serif, AND Mono variants
    #   • font-liberation → includes Liberation Sans, Sans Narrow, Serif, AND Mono
    # Fonts not in any cask get a fallback manual-download URL shown at the end.
    CASKS = [
        # Sans-serif / Modern
        ("Open Sans",        ["font-open-sans"]),
        ("Roboto",           ["font-roboto"]),
        ("Ubuntu",           ["font-ubuntu"]),
        ("Cantarell",        ["font-cantarell"]),
        ("Noto Sans",        ["font-noto-sans"]),
        ("Noto Serif",       ["font-noto-serif"]),
        ("Inconsolata",      ["font-inconsolata"]),
        ("Hack",             ["font-hack"]),
        ("DejaVu",           ["font-dejavu"]),          # Sans + Serif + Mono
        ("Liberation",       ["font-liberation"]),      # Sans + Sans Narrow + Serif + Mono
        ("Carlito",          ["font-carlito"]),
        ("Caladea",          ["font-caladea"]),
        # Serif / Editorial
        ("EB Garamond",      ["font-eb-garamond"]),
        ("Vollkorn",         ["font-vollkorn"]),
        ("Lora",             ["font-lora"]),
        ("GNU FreeFont",     ["font-freefont", "font-gnu-freefont",
                              "font-gnu-free", "font-free-mono"]),  # FreeSans+FreeSerif+FreeMono
        ("Linux Libertine",  ["font-linux-libertine"]),
        # Decorative / special
        ("Jura",             ["font-jura"]),
        ("M Plus 1",         ["font-m-plus-1", "font-m-plus", "font-mplus-1"]),
    ]

    # Fonts that have no Homebrew cask — provide a direct download URL instead
    MANUAL_DOWNLOADS = {
        "GNU FreeFont": "https://savannah.gnu.org/projects/freefont/",
    }

    # Verify brew is available
    result = subprocess.run(["which", "brew"], capture_output=True)
    if result.returncode != 0:
        print("❌  Homebrew not found. Install it from https://brew.sh then re-run.")
        sys.exit(1)

    ok, manually_needed = 0, []

    for label, alternatives in CASKS:
        print(f"  ↳ {label} ...", end=" ", flush=True)
        installed = False

        for cask in alternatives:
            r = subprocess.run(
                ["brew", "install", "--cask", cask],
                capture_output=True, text=True
            )
            if r.returncode == 0 or "already installed" in r.stdout + r.stderr:
                status = "already installed" if "already installed" in r.stdout + r.stderr else "✓"
                print(status)
                ok += 1
                installed = True
                break

        if not installed:
            tried = ", ".join(alternatives)
            print(f"⚠  not in cask repo (tried: {tried})")
            manually_needed.append(label)

    # Refresh font cache
    subprocess.run(["fc-cache", "-fv"], capture_output=True)

    print(f"\n✅  Done: {ok} installed via Homebrew, {len(manually_needed)} need manual install.")

    if manually_needed:
        print("\n📥  Manual download needed for:")
        for label in manually_needed:
            url = MANUAL_DOWNLOADS.get(label, "https://fonts.google.com")
            print(f"    • {label:<16}  →  {url}")
        print()
        print("   After downloading, drag the .ttf/.otf files into Font Book.app")


def main():
    print_font_list()

    if "--install" not in sys.argv:
        print("  ℹ  Dry-run mode. Run with --install to actually install fonts.")
        print("  ℹ  Inside Docker: fonts are installed automatically by the Dockerfile.\n")
        return

    os_name = platform.system()
    if os_name == "Linux":
        install_linux()
    elif os_name == "Darwin":
        install_macos()
    else:
        print(f"\n⚠  Unsupported OS: {os_name}")
        print("   Please install fonts manually. See the Dockerfile for the full list.\n")


if __name__ == "__main__":
    main()
