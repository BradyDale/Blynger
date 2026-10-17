#!/bin/zsh
set -euo pipefail

source_root=${0:A:h:h}
destination=${1:-"$HOME/Applications/Blynger.app"}
temporary=$(mktemp -d "${TMPDIR:-/tmp}/blynger-build.XXXXXX")
trap 'rm -rf "$temporary"' EXIT
bundle="$temporary/Blynger.app"
mkdir -p "$bundle/Contents/MacOS" "$bundle/Contents/Resources"

version=$(/usr/bin/python3 -c 'import sys; sys.path.insert(0,sys.argv[1]); from version import APP_VERSION; print(APP_VERSION)' "$source_root")
/usr/bin/xcrun swiftc -module-cache-path "$temporary/module-cache" "$source_root/native/Main.swift" -o "$bundle/Contents/MacOS/Blynger" -framework Cocoa -framework WebKit
/bin/cp "$source_root/native/Info.plist" "$bundle/Contents/Info.plist"
/bin/cp "$source_root/native/Blynger.icns" "$bundle/Contents/Resources/Blynger.icns"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $version" "$bundle/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion $version" "$bundle/Contents/Info.plist"

# With no Apple Development certificate installed, an explicit designated
# requirement gives every local rebuild the same identity. macOS can therefore
# remember the user's Documents-folder decision across application updates.
/usr/bin/codesign --force --deep --sign - --requirements '=designated => identifier "com.bradydale.blynger"' "$bundle"
/usr/bin/codesign --verify --deep --strict "$bundle"

if [[ -e "$destination" ]]; then
  # User Applications folders managed by Finder or a sync provider can reject
  # an atomic rename of the existing bundle. Updating it with ditto preserves
  # its stable location (and macOS privacy grant) while replacing its contents.
  /usr/bin/ditto "$bundle" "$destination"
else
  /bin/mv "$bundle" "$destination"
fi
# Finder and cloud providers can attach extended metadata while replacing an
# existing bundle. Remove it before the final signature so Launch Services does
# not reject an otherwise complete executable as a malformed application.
/usr/bin/xattr -cr "$destination"
/usr/bin/xattr -d com.apple.FinderInfo "$destination" 2>/dev/null || true
/usr/bin/xattr -d 'com.apple.fileprovider.fpfs#P' "$destination" 2>/dev/null || true
/usr/bin/codesign --force --deep --sign - --requirements '=designated => identifier "com.bradydale.blynger"' "$destination"
/usr/bin/codesign --verify --deep --strict "$destination"
echo "Installed Blynger $version at $destination"
