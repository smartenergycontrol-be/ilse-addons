#!/usr/bin/with-contenv sh
# with-contenv: the s6 base image scrubs the environment, SUPERVISOR_TOKEN would not reach the app
exec python3 -m ilse_s2.main --options /data/options.json
