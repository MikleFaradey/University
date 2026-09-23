#!/bin/bash
set -e

if [ "$(id -u)" -ne 0 ]; then
    exec sudo "$0" "$@"
fi

clean_home() {
    home_dir="$1"
    [ -d "$home_dir" ] || return 0
    rm -rf "$home_dir/.config/interchange"
    rm -rf "$home_dir/.interchange"
    rm -rf "$home_dir/InterchangeReceived"
    rm -rf "$home_dir/InterchangeServerReceived"
    rm -rf "$home_dir/Library/Application Support/Interchange"
    rm -rf "$home_dir/Library/Caches/Interchange"
    rm -f "$home_dir/Library/Preferences/com.interchange.client.plist"
}

clean_home /var/root

for home_dir in /Users/*; do
    [ -d "$home_dir" ] || continue
    clean_home "$home_dir"
done

rm -rf "/Applications/Interchange.app"
rm -rf "/Library/Application Support/Interchange"
rm -rf "/Library/Caches/Interchange"

echo "Interchange removed."
