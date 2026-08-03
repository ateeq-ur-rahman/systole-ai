Place app icons here before running `npm run tauri build`:

  32x32.png
  128x128.png
  128x128@2x.png
  icon.icns   (macOS, optional)
  icon.ico    (Windows, required for the .exe/.msi bundle)

Generate the full set from a single 1024x1024 source image with:

  npx @tauri-apps/cli icon path/to/systole-mark.png

This writes all required sizes/formats into this folder automatically.
