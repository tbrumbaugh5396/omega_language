#!/bin/bash
# Remove the venv and the Desktop .app. Your data/ folder is kept unless you
# answer yes to the second question.
cd "$(dirname "$0")/.."
echo "  This removes the .venv and the Desktop app launcher."
read -p "  Continue? [y/N] " yn
[ "$yn" = "y" ] || [ "$yn" = "Y" ] || exit 0
rm -rf .venv
rm -rf "$HOME/Desktop/MacroKitchen.app"
echo "  ✓ removed"
read -p "  Also delete ALL data (ingredients, recipes, logs, weight history)? [y/N] " yn
if [ "$yn" = "y" ] || [ "$yn" = "Y" ]; then
  rm -rf data
  echo "  ✓ data deleted"
fi
read -p "  Press enter to close."
