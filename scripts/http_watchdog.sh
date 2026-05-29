#!/bin/bash
# HTTP Watchdog — следит за портом 8090, перезапускает если 502/недоступен
LOG=/root/my_personal_ai/logs/http_watchdog.log
FAILS=0
MAX_FAILS=3

while true; do
    HTTP_CODE=$(curl -sf -o /dev/null -w '%{http_code}' http://localhost:8090/api/status 2>/dev/null)
    if [ "$HTTP_CODE" = "200" ]; then
        if [ $FAILS -gt 0 ]; then
            echo "$(date '+%Y-%m-%d %H:%M:%S') [RECOVER] HTTP 200 after $FAILS fails" >> $LOG
        fi
        FAILS=0
    else
        FAILS=$((FAILS+1))
        echo "$(date '+%Y-%m-%d %H:%M:%S') [FAIL $FAILS/$MAX_FAILS] HTTP=${HTTP_CODE:-timeout}" >> $LOG
        if [ $FAILS -ge $MAX_FAILS ]; then
            echo "$(date '+%Y-%m-%d %H:%M:%S') [RESTART] Restarting personal-ai.service" >> $LOG
            systemctl restart personal-ai.service
            FAILS=0
            sleep 20
        fi
    fi
    sleep 15
done
