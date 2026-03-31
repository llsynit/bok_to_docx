#!/usr/bin/env bash
# Purpose: Prepares and pushes a new git commit.
# Usage:   ./push.sh <branch_name> <commit_message>    (f.eks. $0 main "Melding")
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Manglende argument for github opplasting."
  echo 'Bruk: $0 <branch_name> <commit_message>    (f.eks. $0 main "Melding")'
  exit 3
fi

BRANCH_NAME="$(git rev-parse --abbrev-ref HEAD)"
if [[ $1 != "$BRANCH_NAME" ]]; then
  echo "Oppgit branch $1 matcher ikke ikke ${BRANCH_NAME}."
  exit 4
fi

git fetch
if git ls-remote --exit-code origin $1 > /dev/null 2>&1; then
  BEHIND="$(git rev-list HEAD..origin/$1 --count)"
  if [[ $BEHIND -gt 0 ]]; then
    echo "Du er $BEHIND commits back branch $1."
    read -p "Fortsette likevel? [y,n]: " answer
    if [[ "$answer" != "y" ]]; then
      echo "Avbrutt."
      exit 5
    fi
  fi
fi

git status
git add .
echo "Alle nye filer lagt til."
git commit -m "$2"
git push origin $1

echo "Prosjekt oppdatert på GitHub på branch $1."