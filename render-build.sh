#!/usr/bin/env bash
# exit on error
set -o errexit

# Instalar dependencias de Python
pip install -r requirements.txt

# Si estamos en Render, instalamos pg_dump localmente
if [[ -n "$RENDER" ]]; then
  echo "Configurando pg_dump para Render..."
  
  # 1. Intentar encontrarlo en el sistema primero
  SYS_PG_DUMP=$(which pg_dump || true)
  if [[ -n "$SYS_PG_DUMP" ]]; then
    echo "pg_dump encontrado en el sistema: $SYS_PG_DUMP"
    ln -sf "$SYS_PG_DUMP" ./pg_dump_render
  else
    # 2. Si no está, descargamos un paquete compatible (Ubuntu 22.04/24.04)
    echo "pg_dump no encontrado. Descargando binario..."
    # Usamos un mirror de Ubuntu que es más estable que el de Debian
    URL="http://archive.ubuntu.com/ubuntu/pool/main/p/postgresql-16/postgresql-client-16_16.2-1ubuntu4_amd64.deb"
    
    if curl -sLf "$URL" -o pg_client.deb; then
      ar x pg_client.deb
      tar -xf data.tar.xz
      # El binario suele estar en usr/bin/pg_dump dentro del tar
      cp ./usr/bin/pg_dump ./pg_dump_render
      chmod +x ./pg_dump_render
      echo "pg_dump instalado localmente en ./pg_dump_render"
    else
      echo "Error al descargar pg_dump. El backup podría fallar."
    fi
  fi
fi
