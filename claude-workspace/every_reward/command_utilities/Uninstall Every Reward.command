#!/bin/bash
# Remove the venv and the Desktop app. Your data folder is NOT deleted unless
# you say yes to the second question.
cd "$(dirname "$0")/.."
echo "  Every Reward — uninstall"
read -p "  Remove the virtual environment (.venv)? [y/N] " yn
if [ "$yn" = "y" ] || [ "$yn" = "Y" ]; then
  rm -rf .venv && echo "  ✓ removed .venv"
fi
if [ -d "$HOME/Desktop/Every Reward.app" ]; then
  read -p "  Remove the Desktop app icon? [y/N] " yn
  if [ "$yn" = "y" ] || [ "$yn" = "Y" ]; then
    rm -rf "$HOME/Desktop/Every Reward.app" && echo "  ✓ removed Desktop app"
  fi
fi
echo
echo "  Your data (database, config, backups) is untouched in ./data —"
echo "  delete that folder yourself if you truly want everything gone."
read -p "  Press enter to close."
