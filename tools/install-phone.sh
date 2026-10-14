#!/bin/bash
# Builds Budget and installs it on the iPhone (plugged in, or on the same Wi-Fi, unlocked).
# Free Apple developer signing lasts 7 days; run this before it runs out. Prints the new expiry.
set -e
cd "$(dirname "$0")/../ios"
UDID=${GYM_PHONE:-00008150-001C09C01EC1401C}
echo "Building…"
xcodebuild -project Budget.xcodeproj -scheme Budget -configuration Release -destination 'generic/platform=iOS' \
  -derivedDataPath build -allowProvisioningUpdates build 2>&1 | grep -E "error:|BUILD (SUCCEEDED|FAILED)" | sort -u
APP=build/Build/Products/Release-iphoneos/Budget.app
for i in 1 2 3; do
  if xcrun devicectl device install app --device "$UDID" "$APP" 2>&1 | grep -q "bundleID: com.wavymaso.budget"; then
    EXP=$(security cms -D -i "$APP/embedded.mobileprovision" 2>/dev/null | plutil -extract ExpirationDate raw -)
    SECS=$(date -j -u -f "%Y-%m-%dT%H:%M:%SZ" "$EXP" "+%s" 2>/dev/null)
    echo "Installed. Works until $(date -r "$SECS" "+%A %-d %B, %H:%M") (then run this again)."
    exit 0
  fi
  echo "Couldn't reach the iPhone (attempt $i). Is it unlocked and connected?"; sleep 5
done
exit 1
