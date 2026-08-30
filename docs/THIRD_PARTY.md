# Third-party runtime files

## Android SDK Platform-Tools

The `bin/platform-tools/` directory contains the Linux build of Android SDK
Platform-Tools revision **37.0.0**. The checked-in revision is recorded in
`bin/platform-tools/source.properties`, and Google's bundled license and
attribution text is retained in `bin/platform-tools/NOTICE.txt`.

The backend's optional ADB installer downloads the current Linux package from:

`https://dl.google.com/android/repository/platform-tools-latest-linux.zip`

Release ZIPs include the recorded revision and notice. Every release workflow
also publishes a SHA-256 checksum for the complete plugin ZIP. This documents the
origin and local package identity; it is not a claim that the checked-in binaries
were independently reproduced from Android source.

When Platform-Tools is updated, update the entire directory from one official
archive, retain `NOTICE.txt` and `source.properties`, run the package check, and
record the revision change in the pull request.
