:: Hermes KB Windows Service Install
:: Run as Administrator (right-click cmd -> "Run as Administrator")

set BASE=D:\hermes-kb\kb
set NSSM=D:\hermes-kb\nssm\nssm.exe
set PYTHON=C:\Users\qqmin06\python-sdk\python3.13.2\python.exe

echo === Hermes KB Service Install ===
echo.

echo [1/2] Stopping old services...
%NSSM% stop hermes-web       2>nul
%NSSM% remove hermes-web confirm 2>nul
%NSSM% stop hermes-tunnel    2>nul
%NSSM% remove hermes-tunnel confirm 2>nul

echo [2/2] Installing hermes-web...
%NSSM% install hermes-web %PYTHON% api\web_server.py
%NSSM% set hermes-web AppDirectory %BASE%
%NSSM% set hermes-web DisplayName "Hermes KB Web Server"
%NSSM% set hermes-web Start SERVICE_AUTO_START

echo [3/3] Installing hermes-tunnel...
%NSSM% install hermes-tunnel %BASE%\cloudflared.exe "tunnel --config %BASE%\cloudflared\config.yml run hermes-kb"
%NSSM% set hermes-tunnel AppDirectory %BASE%
%NSSM% set hermes-tunnel DisplayName "Hermes KB Cloudflare Tunnel"
%NSSM% set hermes-tunnel Start SERVICE_AUTO_START
%NSSM% set hermes-tunnel DependOnService hermes-web

echo.
echo Starting services...
%NSSM% start hermes-web
timeout /t 3 >nul
%NSSM% start hermes-tunnel

echo.
echo === Done ===
echo Visit: https://zs.captainxq.me
