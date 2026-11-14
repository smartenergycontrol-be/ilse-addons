# Wordt in run.sh gesourcet, vóór de opbouw van TAILSCALE_FLAGS.
# hostname-optie met "{mac}" (bv. "ilse-{mac}") wordt bij de EERSTE start omgezet naar een vaste naam
# uit de MAC van de vaste netwerkkaart (laatste 6 hex-tekens) en bewaard in /data/sec-hostname.
# Volgende starts lezen dat bestand: de naam verandert nooit meer, ook niet als er later een
# netwerkkaart of wifi bijkomt.

sec_primary_mac() {
  local i best=""
  # 1. vaste, bedrade kaart: heeft een fysiek toestel, is geen wifi, type 1 (ethernet); alfabetisch eerste
  for i in $(ls /sys/class/net | sort); do
    [ -e "/sys/class/net/$i/device" ] || continue
    [ -d "/sys/class/net/$i/wireless" ] && continue
    [ "$(cat /sys/class/net/$i/type 2>/dev/null)" = 1 ] || continue
    best=$i; break
  done
  # 2. anders: eerste fysieke kaart (ook wifi)
  if [ -z "$best" ]; then
    for i in $(ls /sys/class/net | sort); do
      [ -e "/sys/class/net/$i/device" ] && { best=$i; break; }
    done
  fi
  [ -n "$best" ] || return 1
  local mac
  mac=$(cat "/sys/class/net/$best/address" 2>/dev/null | tr -d ':' | tr 'A-F' 'a-f')
  echo "$mac" | grep -Eq '^[0-9a-f]{12}$' || return 1
  [ "$mac" != 000000000000 ] || return 1
  echo "$mac"
}

sec_resolve_hostname() {   # $1 = optiewaarde; print de naam die naar tailscale gaat
  local tpl=$1 store=/data/sec-hostname mac name
  case "$tpl" in *"{mac}"*) ;; *) echo "$tpl"; return 0;; esac
  if [ -s "$store" ]; then cat "$store"; return 0; fi
  if mac=$(sec_primary_mac); then
    name=${tpl//\{mac\}/${mac:6:6}}
  else
    # geen bruikbare MAC: willekeurig, maar wel vast (wordt bewaard)
    name=${tpl//\{mac\}/x$(head -c 3 /dev/urandom | od -An -tx1 | tr -d ' \n' | cut -c1-5)}
  fi
  echo "$name" > "$store"
  echo "$name"
}
