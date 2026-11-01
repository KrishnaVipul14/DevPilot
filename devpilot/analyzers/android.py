"""Android repository analyzer for security, manifest hygiene, SDK targets, and Kotlin/Java code health.

Audits AndroidManifest.xml, Gradle build scripts, and Kotlin/Java application code
against common security vulnerabilities, OWASP Mobile Top 10 recommendations,
and modern Android platform standards (Android 12+ exported flags, SDK targets).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from devpilot.analyzers.base import Analyzer, AnalyzerOutput
from devpilot.core.context import RepoContext
from devpilot.core.models import Confidence, Finding, Severity

ANDROID_NS = "http://schemas.android.com/apk/res/android"

DANGEROUS_PERMISSIONS: dict[str, tuple[Severity, str]] = {
    "android.permission.READ_SMS": (
        Severity.HIGH,
        "Reading SMS messages can expose 2FA OTP codes and sensitive personal conversations.",
    ),
    "android.permission.RECEIVE_SMS": (
        Severity.HIGH,
        "Intercepting incoming SMS can expose authorization tokens and one-time passwords.",
    ),
    "android.permission.SEND_SMS": (
        Severity.HIGH,
        "Sending SMS messages can trigger unauthorized carrier charges.",
    ),
    "android.permission.READ_CALL_LOG": (
        Severity.HIGH,
        "Access to user call logs compromises communication history and metadata.",
    ),
    "android.permission.SYSTEM_ALERT_WINDOW": (
        Severity.HIGH,
        "Drawing overlays on top of other apps enables tapjacking and credential phishing.",
    ),
    "android.permission.REQUEST_INSTALL_PACKAGES": (
        Severity.HIGH,
        "Requesting package installations bypasses standard app distribution channels.",
    ),
    "android.permission.WRITE_SETTINGS": (
        Severity.HIGH,
        "Modifying system settings can destabilize device security configurations.",
    ),
    "android.permission.READ_CONTACTS": (
        Severity.MEDIUM,
        "Accessing user address book contacts requires explicit user justification.",
    ),
    "android.permission.RECORD_AUDIO": (
        Severity.MEDIUM,
        "Accessing the microphone allows background audio recording.",
    ),
    "android.permission.ACCESS_FINE_LOCATION": (
        Severity.MEDIUM,
        "Accessing precise GPS location reveals real-time physical movement.",
    ),
}


class AndroidAnalyzer(Analyzer):
    name = "android"
    description = "Android manifest security, build configuration, SDK levels, and Kotlin/Java hygiene"

    def enabled(self, ctx: RepoContext) -> bool:
        if not super().enabled(ctx):
            return False
        return ctx.is_android_project or bool(ctx.android_manifests or ctx.kotlin_files or ctx.java_files)

    def run(self, ctx: RepoContext) -> AnalyzerOutput:
        out = AnalyzerOutput()
        for mf in ctx.android_manifests:
            self._audit_manifest(ctx, mf, out)
        for gf in ctx.gradle_files:
            self._audit_gradle(ctx, gf, out)
        for jf in ctx.jvm_files:
            self._audit_jvm(ctx, jf, out)

        count = len(out.findings)
        out.message = (
            f"Android audit complete ({count} findings across "
            f"{len(ctx.android_manifests)} manifests, {len(ctx.gradle_files)} build files, "
            f"{len(ctx.jvm_files)} Kotlin/Java files)"
        )
        return out

    def _line_of(self, text: str, pattern: str) -> int:
        for idx, line in enumerate(text.splitlines(), start=1):
            if pattern in line:
                return idx
        return 1

    def _line_re(self, text: str, regex: re.Pattern[str]) -> int:
        for idx, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                return idx
        return 1

    def _audit_manifest(self, ctx: RepoContext, rel: str, out: AnalyzerOutput) -> None:
        text = ctx.read_text(rel)
        if not text:
            return
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return

        app_elem = root.find("application")
        if app_elem is not None:
            self._audit_manifest_app_flags(app_elem, rel, text, out)
            self._audit_manifest_components(app_elem, rel, text, out)
        self._audit_manifest_permissions(root, rel, text, out)

    def _audit_manifest_app_flags(
        self, app_elem: ET.Element, rel: str, text: str, out: AnalyzerOutput
    ) -> None:
        debuggable = app_elem.attrib.get(f"{{{ANDROID_NS}}}debuggable")
        if debuggable == "true":
            line = self._line_of(text, "android:debuggable")
            out.add(
                Finding(
                    module=self.name,
                    rule="android-debuggable",
                    severity=Severity.CRITICAL,
                    title="Application is explicitly marked debuggable in manifest",
                    file=rel,
                    line=line,
                    evidence=(
                        '`android:debuggable="true"` allows attackers with physical or ADB access '
                        "to attach debuggers, extract runtime memory, and execute arbitrary code."
                    ),
                    suggestion="Remove `android:debuggable` from AndroidManifest.xml (let Gradle manage it per buildType).",
                    confidence=Confidence.HIGH,
                    fixable=True,
                ),
                anchor=f"{rel}:debuggable",
            )

        cleartext = app_elem.attrib.get(f"{{{ANDROID_NS}}}usesCleartextTraffic")
        if cleartext == "true":
            line = self._line_of(text, "android:usesCleartextTraffic")
            out.add(
                Finding(
                    module=self.name,
                    rule="android-cleartext-traffic",
                    severity=Severity.HIGH,
                    title="Cleartext (HTTP) traffic explicitly permitted",
                    file=rel,
                    line=line,
                    evidence=(
                        '`android:usesCleartextTraffic="true"` permits plaintext HTTP connections, '
                        "exposing user traffic to network interception and man-in-the-middle attacks."
                    ),
                    suggestion='Set `android:usesCleartextTraffic="false"` and enforce HTTPS for all network calls.',
                    confidence=Confidence.HIGH,
                    fixable=True,
                ),
                anchor=f"{rel}:cleartext",
            )

        allow_backup = app_elem.attrib.get(f"{{{ANDROID_NS}}}allowBackup")
        if allow_backup == "true":
            line = self._line_of(text, "android:allowBackup")
            out.add(
                Finding(
                    module=self.name,
                    rule="android-allow-backup",
                    severity=Severity.MEDIUM,
                    title="Full application backup enabled (allowBackup=true)",
                    file=rel,
                    line=line,
                    evidence=(
                        '`android:allowBackup="true"` allows app private databases, preferences, and files '
                        "to be exported via `adb backup`."
                    ),
                    suggestion='Set `android:allowBackup="false"` or define restrictive `android:dataExtractionRules`.',
                    confidence=Confidence.HIGH,
                    fixable=True,
                ),
                anchor=f"{rel}:backup",
            )

    def _audit_manifest_components(
        self, app_elem: ET.Element, rel: str, text: str, out: AnalyzerOutput
    ) -> None:
        for comp_type in ("activity", "service", "receiver", "provider"):
            for comp in app_elem.findall(comp_type):
                c_name = comp.attrib.get(f"{{{ANDROID_NS}}}name", comp_type)
                exported_attr = comp.attrib.get(f"{{{ANDROID_NS}}}exported")
                permission = comp.attrib.get(f"{{{ANDROID_NS}}}permission")
                has_intent_filter = comp.find("intent-filter") is not None

                if has_intent_filter and exported_attr is None:
                    line = self._line_of(text, c_name.rsplit(".", 1)[-1])
                    out.add(
                        Finding(
                            module=self.name,
                            rule="android-exported-missing",
                            severity=Severity.HIGH,
                            title=f"<{comp_type}> `{c_name}` with intent-filter lacks android:exported",
                            file=rel,
                            line=line,
                            evidence=(
                                f"Component `<{comp_type}>` declares an `<intent-filter>` but does not "
                                "specify `android:exported`. This causes build and installation crashes on Android 12+ (API 31+)."
                            ),
                            suggestion='Explicitly declare `android:exported="true"` (if an entry point) or `android:exported="false"`.',
                            confidence=Confidence.HIGH,
                            fixable=True,
                            metadata={"component": c_name, "type": comp_type},
                        ),
                        anchor=f"{rel}:{c_name}:exported-missing",
                    )
                elif exported_attr == "true":
                    is_launcher = False
                    if has_intent_filter and comp_type == "activity":
                        action = comp.find(".//action")
                        cat = comp.find(".//category")
                        if (
                            action is not None
                            and cat is not None
                            and "MAIN" in action.attrib.get(f"{{{ANDROID_NS}}}name", "")
                            and "LAUNCHER" in cat.attrib.get(f"{{{ANDROID_NS}}}name", "")
                        ):
                            is_launcher = True
                    if not is_launcher and not permission:
                        line = self._line_of(text, c_name.rsplit(".", 1)[-1])
                        out.add(
                            Finding(
                                module=self.name,
                                rule="android-exported-no-permission",
                                severity=Severity.HIGH,
                                title=f"Exported <{comp_type}> `{c_name}` not protected by permission",
                                file=rel,
                                line=line,
                                evidence=(
                                    f'`<{comp_type}>` has `android:exported="true"` without an `android:permission`, '
                                    "allowing any third-party app installed on the device to invoke it."
                                ),
                                suggestion=f'Protect `{c_name}` with an `android:permission` or set `android:exported="false"`.',
                                confidence=Confidence.HIGH,
                                metadata={"component": c_name, "type": comp_type},
                            ),
                            anchor=f"{rel}:{c_name}:exported-no-perm",
                        )

    def _audit_manifest_permissions(self, root: ET.Element, rel: str, text: str, out: AnalyzerOutput) -> None:
        for perm in root.findall("uses-permission"):
            p_name = perm.attrib.get(f"{{{ANDROID_NS}}}name", "")
            if p_name in DANGEROUS_PERMISSIONS:
                sev, reason = DANGEROUS_PERMISSIONS[p_name]
                line = self._line_of(text, p_name)
                out.add(
                    Finding(
                        module=self.name,
                        rule="android-dangerous-permission",
                        severity=sev,
                        title=f"High-risk permission requested: {p_name.rsplit('.', 1)[-1]}",
                        file=rel,
                        line=line,
                        evidence=f"Manifest requests `{p_name}`. {reason}",
                        suggestion="Verify necessity, document privacy rationale, and implement runtime permission checks.",
                        confidence=Confidence.HIGH,
                        metadata={"permission": p_name},
                    ),
                    anchor=f"{rel}:{p_name}",
                )

    def _audit_gradle(self, ctx: RepoContext, rel: str, out: AnalyzerOutput) -> None:
        text = ctx.read_text(rel)
        if not text:
            return

        # 1. Outdated minSdk (< 24)
        min_sdk_m = re.search(r"\bminSdk(?:Version)?\s*=?\s*(\d+)", text)
        if min_sdk_m:
            val = int(min_sdk_m.group(1))
            if val < 24:
                line = self._line_re(text, re.compile(r"\bminSdk(?:Version)?\b"))
                out.add(
                    Finding(
                        module=self.name,
                        rule="android-min-sdk-outdated",
                        severity=Severity.MEDIUM,
                        title=f"Outdated minSdk ({val}) below API 24",
                        file=rel,
                        line=line,
                        evidence=(
                            f"`minSdk {val}` supports obsolete Android versions lacking default TLS 1.3, "
                            "modern scoped storage, and contemporary platform security features."
                        ),
                        suggestion="Raise `minSdk` to at least 24 (Android 7.0) or 26 (Android 8.0).",
                        confidence=Confidence.HIGH,
                        metadata={"min_sdk": val},
                    ),
                    anchor=f"{rel}:minsdk",
                )

        # 2. Outdated targetSdk (< 34)
        target_sdk_m = re.search(r"\btargetSdk(?:Version)?\s*=?\s*(\d+)", text)
        if target_sdk_m:
            val = int(target_sdk_m.group(1))
            if val < 34:
                line = self._line_re(text, re.compile(r"\btargetSdk(?:Version)?\b"))
                out.add(
                    Finding(
                        module=self.name,
                        rule="android-target-sdk-outdated",
                        severity=Severity.MEDIUM,
                        title=f"targetSdk ({val}) is below Google Play API 34 requirement",
                        file=rel,
                        line=line,
                        evidence=(
                            f"`targetSdk {val}` does not meet current Google Play target API standards (API 34+) "
                            "and misses modern privacy protections (notification permissions, photo picker restrictions)."
                        ),
                        suggestion="Update `targetSdk` to 34 or 35.",
                        confidence=Confidence.HIGH,
                        metadata={"target_sdk": val},
                    ),
                    anchor=f"{rel}:targetsdk",
                )

        # 3. Insecure repository URL (http://)
        http_repo_m = re.search(r"url\s*=?\s*['\"](http://[^'\"]+)['\"]", text)
        if http_repo_m:
            url = http_repo_m.group(1)
            line = self._line_of(text, url)
            out.add(
                Finding(
                    module=self.name,
                    rule="android-insecure-repo-url",
                    severity=Severity.HIGH,
                    title="Insecure HTTP repository URL in build script",
                    file=rel,
                    line=line,
                    evidence=(
                        f"Repository URL `{url}` uses plaintext HTTP. "
                        "Dependencies can be tampered with in transit via man-in-the-middle attacks."
                    ),
                    suggestion="Replace `http://` with `https://`.",
                    confidence=Confidence.HIGH,
                    fixable=True,
                    metadata={"url": url},
                ),
                anchor=f"{rel}:{url}",
            )

        # 4. Hardcoded keystore password in build script
        pass_m = re.search(r"(?:storePassword|keyPassword)\s*=?\s*['\"]([^'\"]{3,})['\"]", text)
        if pass_m:
            line = self._line_re(text, re.compile(r"(?:storePassword|keyPassword)\s*="))
            out.add(
                Finding(
                    module=self.name,
                    rule="android-hardcoded-keystore-password",
                    severity=Severity.HIGH,
                    title="Keystore signing credentials hardcoded in Gradle script",
                    file=rel,
                    line=line,
                    evidence="Hardcoded signing passwords in build files can leak release keys if repository is shared or exposed.",
                    suggestion="Read passwords from environment variables or `gradle.properties` outside version control.",
                    confidence=Confidence.HIGH,
                ),
                anchor=f"{rel}:keystore-pwd",
            )

    def _audit_jvm(self, ctx: RepoContext, rel: str, out: AnalyzerOutput) -> None:
        text = ctx.read_text(rel)
        if not text:
            return

        lines = text.splitlines()

        for idx, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("//") or stripped.startswith("/*"):
                continue

            # 1. Insecure WebView JavaScript
            if "setJavaScriptEnabled(true)" in stripped or "javaScriptEnabled = true" in stripped:
                out.add(
                    Finding(
                        module=self.name,
                        rule="android-insecure-webview-js",
                        severity=Severity.MEDIUM,
                        title="WebView JavaScript execution enabled",
                        file=rel,
                        line=idx,
                        evidence=(
                            "JavaScript execution is enabled on a WebView. If untrusted content or external URLs "
                            "are rendered, this enables Cross-Site Scripting (XSS) and bridge manipulation."
                        ),
                        suggestion="Ensure WebView only loads trusted first-party HTTPS origins, and sanitize all input.",
                        confidence=Confidence.MEDIUM,
                    ),
                    anchor=f"{rel}:{idx}:webview-js",
                )

            # 2. Insecure WebView Local File Access
            if (
                "setAllowFileAccess(true)" in stripped
                or "allowFileAccess = true" in stripped
                or "setAllowUniversalAccessFromFileURLs(true)" in stripped
                or "setAllowFileAccessFromFileURLs(true)" in stripped
            ):
                out.add(
                    Finding(
                        module=self.name,
                        rule="android-webview-file-access",
                        severity=Severity.HIGH,
                        title="WebView local file access enabled",
                        file=rel,
                        line=idx,
                        evidence=(
                            "Enabling local file access in WebViews allows attackers who can inject scripts to read "
                            "private application storage files."
                        ),
                        suggestion="Keep `allowFileAccess = false` and use `androidx.webkit.WebViewAssetLoader`.",
                        confidence=Confidence.HIGH,
                    ),
                    anchor=f"{rel}:{idx}:webview-file",
                )

            # 3. Insecure Cryptography / Cipher Mode (ECB mode)
            if "AES/ECB" in stripped or 'Cipher.getInstance("DES' in stripped:
                out.add(
                    Finding(
                        module=self.name,
                        rule="android-insecure-cipher",
                        severity=Severity.HIGH,
                        title="Insecure cipher mode or broken encryption algorithm",
                        file=rel,
                        line=idx,
                        evidence="AES in ECB mode does not use an initialization vector and reveals repeating data patterns.",
                        suggestion='Use `"AES/GCM/NoPadding"` or `"AES/CBC/PKCS7Padding"` with a cryptographically random IV.',
                        confidence=Confidence.HIGH,
                    ),
                    anchor=f"{rel}:{idx}:ecb",
                )

            # 4. Weak Hashing (MD5 / SHA-1)
            if (
                'MessageDigest.getInstance("MD5")' in stripped
                or 'MessageDigest.getInstance("SHA-1")' in stripped
            ):
                out.add(
                    Finding(
                        module=self.name,
                        rule="android-weak-hash",
                        severity=Severity.MEDIUM,
                        title="Weak cryptographic hash algorithm (MD5/SHA-1)",
                        file=rel,
                        line=idx,
                        evidence="MD5 and SHA-1 are cryptographically broken and prone to collision attacks.",
                        suggestion='Use `"SHA-256"`, `"SHA-512"`, or HMAC-SHA256.',
                        confidence=Confidence.HIGH,
                    ),
                    anchor=f"{rel}:{idx}:weak-hash",
                )

            # 5. Insecure storage permissions (MODE_WORLD_READABLE / WRITEABLE)
            if "MODE_WORLD_READABLE" in stripped or "MODE_WORLD_WRITEABLE" in stripped:
                out.add(
                    Finding(
                        module=self.name,
                        rule="android-world-readable-storage",
                        severity=Severity.HIGH,
                        title="Insecure world-accessible file permissions",
                        file=rel,
                        line=idx,
                        evidence="`MODE_WORLD_READABLE` or `MODE_WORLD_WRITEABLE` allows any other app on the device to read or write this file.",
                        suggestion="Use `MODE_PRIVATE` or `EncryptedSharedPreferences` from Android Jetpack Security.",
                        confidence=Confidence.HIGH,
                    ),
                    anchor=f"{rel}:{idx}:world-readable",
                )

            # 6. Missing PendingIntent Mutability Flag (Android 12+ crash & hijack risk)
            if "PendingIntent.get" in stripped and not any(
                flag in stripped for flag in ("FLAG_IMMUTABLE", "FLAG_MUTABLE")
            ):
                out.add(
                    Finding(
                        module=self.name,
                        rule="android-pending-intent-missing-mutability",
                        severity=Severity.HIGH,
                        title="PendingIntent missing FLAG_IMMUTABLE or FLAG_MUTABLE",
                        file=rel,
                        line=idx,
                        evidence=(
                            "Android 12+ requires explicit mutability flags on all PendingIntents. "
                            "Missing flags cause runtime crashes and expose intents to modification."
                        ),
                        suggestion="Add `PendingIntent.FLAG_IMMUTABLE` (or `PendingIntent.FLAG_MUTABLE` if explicitly required).",
                        confidence=Confidence.HIGH,
                    ),
                    anchor=f"{rel}:{idx}:pending-intent",
                )

        # 7. Check for empty TLS TrustManager (disables certificate validation)
        if "X509TrustManager" in text or "TrustManager" in text:
            empty_tm = re.search(
                r"checkServerTrusted\s*\([^)]*\)\s*\{\s*(?:/\*.*?\*/)?\s*\}",
                text,
                re.DOTALL,
            )
            if empty_tm:
                line = self._line_re(text, re.compile(r"checkServerTrusted"))
                out.add(
                    Finding(
                        module=self.name,
                        rule="android-insecure-trustmanager",
                        severity=Severity.CRITICAL,
                        title="TLS server certificate verification disabled",
                        file=rel,
                        line=line,
                        evidence=(
                            "Empty `checkServerTrusted` implementation disables all SSL/TLS certificate validation, "
                            "allowing any adversary on the network to intercept or manipulate HTTPS requests."
                        ),
                        suggestion="Remove custom TrustManager and utilize standard Android Network Security Config.",
                        confidence=Confidence.HIGH,
                    ),
                    anchor=f"{rel}:trustmanager",
                )
