# Preflight do ambiente local — Cifra

**Data:** 2026-08-29
**Status:** APROVADO — ambiente completo verificado, incluindo Android local

## Resultado executado

| Componente | Resultado real | Status |
|---|---|---|
| Docker CLI | 29.7.2 | OK |
| Docker Compose | v5.4.0 | OK |
| Docker daemon | 29.7.2, respondendo | OK |
| Node.js | v22.23.2 | OK |
| npm | 10.9.8 | OK |
| Python | 3.11.16 | OK |
| uv | 0.12.6 | OK |
| pnpm | 11.24.0 — instalado globalmente e verificado em 29/08 | OK |
| Corepack | wrapper presente, mas quebrado por conversão de path MSYS (`C:\c\Users\...`) | NÃO USAR |
| Expo CLI | 57.0.20 via `npx` | OK para criação/execução |
| EAS CLI | 23.0.0 via `npx` | OK para build remoto |
| Java/JDK | Temurin 17.0.20.1 em `%LOCALAPPDATA%\Java\jdk-17`; `JAVA_HOME` persistido | OK |
| Android Studio | 2026.1.3.7 instalado em `C:\Program Files\Android\Android Studio`; runtime interno JDK 25.0.2 | OK |
| Android SDK/ADB | SDK em `%LOCALAPPDATA%\Android\Sdk`; ADB 37.0.1; `ANDROID_HOME` e `ANDROID_SDK_ROOT` persistidos | OK |
| Android platform/build-tools | Android 36 + build-tools 36.0.0 | OK |
| Android Emulator | 37.1.11; WHPX instalado e utilizável | OK |
| Android system image | Android 36 Google APIs x86_64 | OK |
| AVD | `Cifra_API_36`, Pixel 7; cold boot real completado em 189,52 s; Android 16 confirmado via ADB | OK |

## Interpretação

O ambiente está pronto para iniciar a F0 e também para build/emulação Android local. FastAPI, Next.js, pnpm, Docker, Expo, EAS, JDK, SDK, ADB e Android Studio foram verificados por execução real.

O AVD `Cifra_API_36` foi inicializado em modo headless, apareceu via ADB como `sdk_gphone64_x86_64`, reportou Android 16 e completou o cold boot. WHPX está instalado e utilizável.

## Ação técnica concluída

pnpm 11.24.0 foi instalado globalmente via npm e verificado. O Corepack quebrado não será usado neste ambiente.

## Decisão operacional

- F0–F5: Docker + web + API; mobile disponível via Expo Go, EAS ou AVD local.
- F6: usar `Cifra_API_36` como emulador de referência e manter teste em Android físico antes de fechar a fase.
