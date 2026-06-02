chcp 65001 >nul
set NSSM=D:\hermes-kb\nssm\nssm.exe

%NSSM% stop hermes-tunnel  2>nul
%NSSM% stop hermes-web     2>nul

%NSSM% start hermes-web
timeout /t 30 /nobreak
%NSSM% start hermes-tunnel

echo.
%NSSM% status hermes-web
%NSSM% status hermes-tunnel
pause
