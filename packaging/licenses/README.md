# Setup component licenses

- `apple-mobile-device-support.rtf` is the unmodified `SLA / Memo` control text
  from Apple's official **Apple Mobile Device Support 19.4.0.10 x64** MSI.
  SHA-256 of the MSI: `b60533fb54e7bd81ffc52d99678a9cce04e58cb54a76281bd7b1309f20d360e9`.
  Its official URL and expected hash are pinned in `padbridge_app/windows/components.py`;
  the matching manifest is in [Microsoft's WinGet repository](https://github.com/microsoft/winget-pkgs/tree/master/manifests/a/Apple/AppleMobileDeviceSupport/19.4.0.10).
  Only this license is redistributed. Setup downloads the signed MSI directly from
  Apple when USB support is missing. The combined installer license displays these
  terms before installation; USB support is not downloaded on ordinary app startup.
- `virtual-display-driver.txt` is the MIT license from
  [VirtualDrivers 25.7.23](https://github.com/VirtualDrivers/Virtual-Display-Driver/blob/25.7.23/LICENSE).
  The pinned, signed driver archive is bundled unchanged; its URL and SHA-256 are
  defined in `padbridge_app/windows/driver_setup.py`.

Update the corresponding license and pin together when changing a component version.
