#!/bin/bash

# Mask Bridge - macOS Code Signing & Notarization Script
# Run AFTER build_backend_optimized.sh, BEFORE package_plugin.sh
#
# Prerequisites:
#   1. Apple Developer Program membership (99$/year)
#   2. "Developer ID Application" certificate installed in Keychain
#   3. Notarization credentials stored in Keychain:
#      xcrun notarytool store-credentials "MaskBridge-Notarize" \
#        --apple-id "your@email.com" \
#        --team-id "J4R32K4N47" \
#        --password "xxxx-xxxx-xxxx-xxxx"
#
# Usage:
#   ./codesign_and_notarize.sh                    # Sign + notarize
#   ./codesign_and_notarize.sh --sign-only        # Sign only (skip notarization)
#   ./codesign_and_notarize.sh --notarize-only    # Submit existing signed engine
#   ./codesign_and_notarize.sh --verify-only      # Verify existing signatures

set -e
set -o pipefail
cd "$(dirname "$0")"
ENTITLEMENTS="${ENTITLEMENTS:-$PWD/entitlements.plist}"

# ============================================================================
# CONFIGURATION — Update these values with your Apple Developer credentials
# ============================================================================
DEVELOPER_ID="Developer ID Application: Nicolas Diolez (J4R32K4N47)"
# Auto-detect Keychain profile: prefer new name, fallback to legacy
NOTARIZE_PROFILE="MaskBridge-Notarize"
BUNDLE_DIR="MaskBridge.lrplugin/backend/maskbridge_engine"

# ============================================================================
# Parse arguments
# ============================================================================
SIGN_ONLY=false
VERIFY_ONLY=false
NOTARIZE_ONLY=false

for arg in "$@"; do
    case "$arg" in
        --sign-only)   SIGN_ONLY=true ;;
        --verify-only) VERIFY_ONLY=true ;;
        --notarize-only) NOTARIZE_ONLY=true ;;
        *) echo "Unknown argument: $arg"; exit 2 ;;
    esac
done

if { [ "$SIGN_ONLY" = true ] && [ "$NOTARIZE_ONLY" = true ]; } || { [ "$VERIFY_ONLY" = true ] && { [ "$SIGN_ONLY" = true ] || [ "$NOTARIZE_ONLY" = true ]; }; }; then
    echo "Choose only one execution mode."
    exit 2
fi

echo "═══════════════════════════════════════════════════════════════════"
echo "    Mask Bridge - macOS Code Signing & Notarization"
echo "═══════════════════════════════════════════════════════════════════"

# ============================================================================
# Preflight checks
# ============================================================================
if [ ! -d "$BUNDLE_DIR" ]; then
    echo "❌ Bundle directory not found: $BUNDLE_DIR"
    echo "   Run build_backend_optimized.sh first."
    exit 1
fi

if [ ! -f "$BUNDLE_DIR/maskbridge_engine" ]; then
    echo "❌ Binary not found: $BUNDLE_DIR/maskbridge_engine"
    echo "   Run build_backend_optimized.sh first."
    exit 1
fi

if [ ! -f "$ENTITLEMENTS" ]; then
    echo "❌ Entitlements file not found: $ENTITLEMENTS"
    exit 1
fi

# Check that the signing identity exists
if ! security find-identity -v -p codesigning | grep -q "$DEVELOPER_ID"; then
    echo "❌ Signing identity not found in Keychain:"
    echo "   $DEVELOPER_ID"
    echo ""
    echo "   Available identities:"
    security find-identity -v -p codesigning
    echo ""
    echo "   To create one: Xcode → Settings → Accounts → Manage Certificates"
    exit 1
fi

echo "✓ Bundle found: $BUNDLE_DIR"
echo "✓ Signing identity: $(echo "$DEVELOPER_ID" | sed 's/Developer ID Application: //')"
echo ""

# ============================================================================
# VERIFY ONLY mode
# ============================================================================
if [ "$VERIFY_ONLY" = true ]; then
    echo "🔍 Verifying existing signatures..."
    echo ""

    # Check main binary
    if codesign --verify --deep --strict "$BUNDLE_DIR/maskbridge_engine" 2>/dev/null; then
        echo "   ✓ maskbridge_engine: valid"
        codesign -d --verbose=2 "$BUNDLE_DIR/maskbridge_engine" 2>&1 | grep "Authority" | head -1
    else
        echo "   ✗ maskbridge_engine: NOT signed or invalid"
        exit 1
    fi

    # Check Gatekeeper assessment
    echo ""
    echo "🛡️  Gatekeeper assessment:"
    codesign -vvvv -R='notarized' --check-notarization "$BUNDLE_DIR/maskbridge_engine"

    exit 0
fi

# ============================================================================
# 1. REMOVE EXISTING SIGNATURES (clean slate)
# ============================================================================
if [ "$NOTARIZE_ONLY" = false ]; then
echo "🧹 Removing existing ad-hoc signatures..."

find "$BUNDLE_DIR" \( -name "*.so" -o -name "*.dylib" \) | while read -r lib; do
    codesign --remove-signature "$lib" 2>/dev/null || true
done
# Python framework binaries (Mach-O without extension, dynamic version search)
find "$BUNDLE_DIR" -path "*/Python.framework/Versions/*/Python" 2>/dev/null | while read -r fw; do
    codesign --remove-signature "$fw" 2>/dev/null || true
done
codesign --remove-signature "$BUNDLE_DIR/maskbridge_engine" 2>/dev/null || true

echo "   ✓ Cleaned"

# ============================================================================
# 2. SIGN ALL .so AND .dylib FILES (inside → outside)
# ============================================================================
echo ""
echo "📝 Signing shared libraries (.so, .dylib)..."

LIB_COUNT=0
LIB_FAIL=0

find "$BUNDLE_DIR" \( -name "*.so" -o -name "*.dylib" \) | while read -r lib; do
    if codesign --force --sign "$DEVELOPER_ID" \
                --timestamp \
                --options runtime \
                "$lib" 2>/dev/null; then
        echo "   ✓ $(basename "$lib")"
    else
        echo "   ✗ FAILED: $(basename "$lib")"
        exit 1
    fi
done

# ============================================================================
# 2b. SIGN Python.framework (Mach-O binary without .so/.dylib extension)
# ============================================================================
find "$BUNDLE_DIR" -path "*/Python.framework/Versions/*/Python" 2>/dev/null | while read -r fw; do
    echo ""
    echo "📝 Signing Python framework ($fw)..."
    codesign --force --sign "$DEVELOPER_ID" \
             --timestamp \
             --options runtime \
             "$fw"
    echo "   ✓ $(basename "$fw")"
done

# ============================================================================
# 3. SIGN THE MAIN EXECUTABLE (must be last)
# ============================================================================
echo ""
echo "📝 Signing main executable with entitlements..."

codesign --force --sign "$DEVELOPER_ID" \
         --timestamp \
         --options runtime \
         --entitlements "$ENTITLEMENTS" \
         "$BUNDLE_DIR/maskbridge_engine"

echo "   ✓ maskbridge_engine"
fi

# ============================================================================
# 4. VERIFY SIGNATURES
# ============================================================================
echo ""
echo "🔍 Verifying signatures..."

if codesign --verify --deep --strict "$BUNDLE_DIR/maskbridge_engine"; then
    echo "   ✓ Deep verification passed"
else
    echo "   ✗ Signature verification FAILED"
    exit 1
fi

echo ""
echo "   Signing authorities:"
codesign -d --verbose=2 "$BUNDLE_DIR/maskbridge_engine" 2>&1 | grep "Authority" || true
echo ""

# ============================================================================
# SIGN ONLY mode — stop here
# ============================================================================
if [ "$SIGN_ONLY" = true ]; then
    echo "═══════════════════════════════════════════════════════════════════"
    echo "    ✅ Code Signing Complete (notarization skipped)"
    echo "═══════════════════════════════════════════════════════════════════"
    exit 0
fi

# ============================================================================
# 5. CREATE ZIP FOR NOTARIZATION
# ============================================================================
if ! xcrun notarytool history --keychain-profile "$NOTARIZE_PROFILE" >/dev/null 2>&1; then
    if xcrun notarytool history --keychain-profile "AutoMask-Notarize" >/dev/null 2>&1; then
        NOTARIZE_PROFILE="AutoMask-Notarize"
    fi
fi

echo "📦 Creating ZIP for notarization submission..."

NOTARIZE_ZIP="MaskBridge_notarize_tmp.zip"
rm -f "$NOTARIZE_ZIP"

# ditto preserves extended attributes & code signatures (unlike zip)
ditto -c -k --sequesterRsrc --keepParent "$BUNDLE_DIR" "$NOTARIZE_ZIP"

echo "   ✓ $NOTARIZE_ZIP ($(du -h "$NOTARIZE_ZIP" | cut -f1))"

# ============================================================================
# 6. SUBMIT TO APPLE FOR NOTARIZATION
# ============================================================================
echo ""
echo "🍎 Submitting to Apple for notarization..."
echo "   (Usually 5-15 min, can take 1-2h when Apple's queue is busy)"
echo ""

# Capture stdout so we can parse the final status (notarytool returns 0
# even when status=Invalid, so we cannot rely on the exit code alone).
NOTARIZE_LOG=$(mktemp -t notarize.XXXXXX)
set +e
xcrun notarytool submit "$NOTARIZE_ZIP" \
    --keychain-profile "$NOTARIZE_PROFILE" \
    --wait | tee "$NOTARIZE_LOG"
NOTARIZE_RET=${PIPESTATUS[0]}
set -e

SUBMISSION_ID=$(grep -E "^[[:space:]]*id:" "$NOTARIZE_LOG" | head -1 | awk '{print $2}')
FINAL_STATUS=$(grep -E "^[[:space:]]*status:" "$NOTARIZE_LOG" | tail -1 | awk '{print $2}')
rm -f "$NOTARIZE_LOG"
rm -f "$NOTARIZE_ZIP"

if [ "$FINAL_STATUS" != "Accepted" ] || [ $NOTARIZE_RET -ne 0 ]; then
    echo ""
    echo "❌ Notarization FAILED (status: ${FINAL_STATUS:-unknown})."
    echo ""
    if [ -n "$SUBMISSION_ID" ]; then
        echo "   Detailed log:"
        echo "   xcrun notarytool log $SUBMISSION_ID --keychain-profile $NOTARIZE_PROFILE"
    fi
    echo ""
    echo "   Common issues:"
    echo "   - Missing --timestamp on codesign"
    echo "   - Missing --options runtime (hardened runtime)"
    echo "   - Unsigned .so / .dylib / framework binary in the bundle"
    exit 1
fi

echo ""
echo "   ✅ Notarization ACCEPTED by Apple (id: $SUBMISSION_ID)"

# ============================================================================
# 7. STAPLING — skipped for standalone Mach-O binaries
# ============================================================================
# `xcrun stapler` only supports .app, .pkg, .dmg bundles. A standalone
# Mach-O executable (our case: PyInstaller OneDir output) cannot have a
# ticket stapled to it (stapler returns error 73 "cannot be stapled").
#
# Consequence: Gatekeeper validates the notarization ONLINE via Apple's
# CloudKit on first launch. Users with internet access (the expected case
# for a Lightroom plugin: download → install → first launch) see no
# warning. Offline-first installs would need .dmg/.pkg packaging.
echo ""
echo "ℹ️  Stapling skipped (not supported for standalone Mach-O binaries)."
echo "   Gatekeeper will validate the notarization online on first launch."

# ============================================================================
# 8. FINAL VERIFICATION
# ============================================================================
echo ""
echo "🔍 Final signature check..."

codesign --verify --deep --strict --verbose=2 "$BUNDLE_DIR/maskbridge_engine"
codesign -vvvv -R='notarized' --check-notarization "$BUNDLE_DIR/maskbridge_engine"

echo ""
echo "═══════════════════════════════════════════════════════════════════"
echo "    ✅ Signing & Notarization Complete!"
echo "═══════════════════════════════════════════════════════════════════"
echo ""
echo "   The binary is signed and notarized by Apple."
echo "   Online Gatekeeper check will succeed on first launch."
echo ""
echo "   Next step: ./package_plugin.sh"
echo ""
