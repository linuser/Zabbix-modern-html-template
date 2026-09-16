#!/usr/bin/env bash
# End-to-end test with a real Zabbix (default 7.0, pick another with ZABBIX_TAG) and Mailpit in Docker. See docs/TESTING.md.
#
#   test/e2e/e2e.sh run        start the stack (if needed), run the scenario - all mails land in Mailpit
#                              (add E2E_SCREENSHOTS=desktop,mobile,dark for a screenshot gallery)
#   test/e2e/e2e.sh previews   screenshot the build's sample-data previews only (no Zabbix)
#   test/e2e/e2e.sh docs       regenerate the README screenshots in docs/img
#   test/e2e/e2e.sh open       open the result gallery and Mailpit in the browser
#   test/e2e/e2e.sh up         start Zabbix + Mailpit only (explore by hand)
#   test/e2e/e2e.sh logs [svc] follow container logs
#   test/e2e/e2e.sh down       stop and delete everything (including the database)
#
# Results: test/e2e/output/index.html   Mails: http://localhost:8025   Zabbix: http://localhost:8080 (Admin / zabbix)
set -euo pipefail
cd "$(dirname "$0")"

compose() { docker compose -f compose.yaml "$@"; }

case "${1:-run}" in
  up)
    compose up -d postgres zabbix-server zabbix-web mailpit assets
    ;;
  run)
    compose up -d postgres zabbix-server zabbix-web mailpit assets
    compose run --rm --build runner scenario
    ;;
  previews)
    compose run --rm --build --no-deps runner previews
    ;;
  docs)
    compose up -d postgres zabbix-server zabbix-web mailpit assets
    compose run --rm --build -v "$(cd ../../docs/img && pwd):/docs-img" runner docs
    ;;
  open)
    [ -f output/index.html ] || { echo "no results yet - run: test/e2e/e2e.sh run"; exit 1; }
    opener=$(command -v open || command -v xdg-open) || { echo "open test/e2e/output/index.html in a browser"; exit 1; }
    "$opener" output/index.html
    "$opener" "http://localhost:${MAILPIT_PORT:-8025}"
    ;;
  logs)
    shift
    compose logs -f "$@"
    ;;
  down)
    compose --profile runner down -v --remove-orphans
    ;;
  *)
    sed -n '2,13p' "$(basename "$0")"
    exit 2
    ;;
esac
