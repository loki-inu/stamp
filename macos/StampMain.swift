import Cocoa
import WebKit

/// Stamp for Mac: one album window. Fetching and drawing stay in the
/// Python package bundled in Resources; this process is the window.
private let paper = NSColor(srgbRed: 239.0 / 255.0, green: 233.0 / 255.0, blue: 221.0 / 255.0, alpha: 1)

@main
struct StampMain {
    static func main() {
        let app = NSApplication.shared
        app.setActivationPolicy(.regular)
        app.delegate = AppDelegate.shared
        app.run()
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate {
    static let shared = AppDelegate()

    private var window: NSWindow!
    private var webView: WKWebView!
    private var server: Process?
    private var endpointFile: URL?
    private let errorLock = NSLock()
    private var errorLog = Data()
    private var quitting = false
    private var reportedFailure = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        buildMenu()
        buildWindow()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            self?.startServer()
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }

    func applicationWillTerminate(_ notification: Notification) {
        quitting = true
        if server?.isRunning == true {
            server?.terminate()
        }
        if let endpointFile {
            try? FileManager.default.removeItem(at: endpointFile)
        }
    }

    // ---------------------------------------------------------------- window

    private func buildWindow() {
        let config = WKWebViewConfiguration()
        let chrome = WKUserScript(
            source: "document.documentElement.dataset.chrome='mac'",
            injectionTime: .atDocumentStart,
            forMainFrameOnly: true
        )
        config.userContentController.addUserScript(chrome)
        webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = self
        webView.allowsBackForwardNavigationGestures = false
        webView.underPageBackgroundColor = paper

        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1120, height: 780),
            styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        window.title = "Stamp"
        window.titlebarAppearsTransparent = true
        window.titleVisibility = .hidden
        window.backgroundColor = paper
        window.minSize = NSSize(width: 760, height: 560)
        window.tabbingMode = .disallowed
        window.contentView = webView
        window.isReleasedWhenClosed = false
        window.center()
    }

    func webView(
        _ webView: WKWebView,
        decidePolicyFor navigationAction: WKNavigationAction,
        decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
    ) {
        guard let url = navigationAction.request.url else {
            decisionHandler(.cancel)
            return
        }
        let local = url.host == "127.0.0.1" || url.host == "localhost" || url.scheme == "about"
        if local {
            decisionHandler(.allow)
            return
        }
        if navigationAction.navigationType == .linkActivated {
            NSWorkspace.shared.open(url)
        }
        decisionHandler(.cancel)
    }

    // ------------------------------------------------------------------ menu

    private func buildMenu() {
        let main = NSMenu()

        let appMenu = NSMenu()
        appMenu.addItem(titled: "About Stamp", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), key: "", target: NSApp)
        appMenu.addItem(.separator())
        appMenu.addItem(titled: "Hide Stamp", action: #selector(NSApplication.hide(_:)), key: "h", target: NSApp)
        appMenu.addItem(titled: "Hide Others", action: #selector(NSApplication.hideOtherApplications(_:)), key: "h", modifiers: [.command, .option], target: NSApp)
        appMenu.addItem(titled: "Show All", action: #selector(NSApplication.unhideAllApplications(_:)), key: "")
        appMenu.addItem(.separator())
        appMenu.addItem(titled: "Quit Stamp", action: #selector(NSApplication.terminate(_:)), key: "q", target: NSApp)
        let appItem = NSMenuItem()
        appItem.submenu = appMenu
        main.addItem(appItem)

        let file = NSMenu(title: "File")
        file.addItem(titled: "Add URL…", action: #selector(addURL(_:)), key: "n", target: self)
        file.addItem(titled: "Print Sheet…", action: #selector(printSheet(_:)), key: "p", target: self)
        file.addItem(.separator())
        file.addItem(titled: "Close", action: #selector(NSWindow.performClose(_:)), key: "w")
        main.addItem(submenu: file)

        let edit = NSMenu(title: "Edit")
        edit.addItem(titled: "Undo", action: Selector(("undo:")), key: "z")
        edit.addItem(titled: "Redo", action: Selector(("redo:")), key: "z", modifiers: [.command, .shift])
        edit.addItem(.separator())
        edit.addItem(titled: "Cut", action: #selector(NSText.cut(_:)), key: "x")
        edit.addItem(titled: "Copy", action: #selector(NSText.copy(_:)), key: "c")
        edit.addItem(titled: "Paste", action: #selector(NSText.paste(_:)), key: "v")
        edit.addItem(titled: "Select All", action: #selector(NSText.selectAll(_:)), key: "a")
        main.addItem(submenu: edit)

        let album = NSMenu(title: "Album")
        album.addItem(titled: "Verify", action: #selector(verifySelected(_:)), key: "v", modifiers: [.command, .shift], target: self)
        album.addItem(titled: "Reveal Album in Finder", action: #selector(revealAlbum(_:)), key: "r", modifiers: [.command, .shift], target: self)
        main.addItem(submenu: album)

        let windowMenu = NSMenu(title: "Window")
        windowMenu.addItem(titled: "Minimize", action: #selector(NSWindow.performMiniaturize(_:)), key: "m")
        windowMenu.addItem(titled: "Zoom", action: #selector(NSWindow.performZoom(_:)), key: "")
        main.addItem(submenu: windowMenu)
        NSApp.windowsMenu = windowMenu
        NSApp.mainMenu = main
    }

    @objc private func addURL(_ sender: Any?) { run("addURL") }
    @objc private func printSheet(_ sender: Any?) { run("printSheet") }
    @objc private func verifySelected(_ sender: Any?) { run("verifySelected") }
    @objc private func revealAlbum(_ sender: Any?) { run("revealAlbum") }

    private func run(_ name: String) {
        webView?.evaluateJavaScript("window.stampNative && window.stampNative.\(name)()") { _, _ in }
    }

    // ---------------------------------------------------------------- server

    private func startServer() {
        guard let resources = resourcesDirectory() else {
            DispatchQueue.main.async {
                self.fail("Stamp is missing its album code.", "The app bundle has no stamp package in Resources. Rebuild it with macos/build-app.sh.")
            }
            return
        }
        guard let python = findPython() else {
            DispatchQueue.main.async {
                self.fail(
                    "Stamp needs Python 3.11 or newer.",
                    "Install it from python.org or with Homebrew (brew install python), then open Stamp again. If it lives somewhere unusual, set STAMP_PYTHON to that python3 program."
                )
            }
            return
        }

        let endpoint = FileManager.default.temporaryDirectory.appendingPathComponent("stamp-endpoint-\(getpid()).txt")
        endpointFile = endpoint
        try? FileManager.default.removeItem(at: endpoint)

        let process = Process()
        process.executableURL = URL(fileURLWithPath: python)
        process.arguments = ["-u", "-m", "stamp.gui", "--no-open", "--endpoint-file", endpoint.path]
        process.currentDirectoryURL = FileManager.default.homeDirectoryForCurrentUser
        var env = ProcessInfo.processInfo.environment
        let pythonPath = resources.path
        if let old = env["PYTHONPATH"], !old.isEmpty {
            env["PYTHONPATH"] = pythonPath + ":" + old
        } else {
            env["PYTHONPATH"] = pythonPath
        }
        env["PYTHONUNBUFFERED"] = "1"
        process.environment = env
        process.standardInput = FileHandle.nullDevice

        let stdout = Pipe()
        let stderr = Pipe()
        process.standardOutput = stdout
        process.standardError = stderr
        stdout.fileHandleForReading.readabilityHandler = { handle in
            let data = handle.availableData
            if data.isEmpty { handle.readabilityHandler = nil }
        }
        stderr.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            if data.isEmpty {
                handle.readabilityHandler = nil
                return
            }
            guard let self else { return }
            self.errorLock.lock()
            self.errorLog.append(data)
            if self.errorLog.count > 8000 {
                self.errorLog.removeFirst(self.errorLog.count - 8000)
            }
            self.errorLock.unlock()
        }
        process.terminationHandler = { [weak self] proc in
            DispatchQueue.main.async {
                guard let self, !self.quitting, proc.terminationStatus != 0 else { return }
                self.fail("The album window stopped.", self.recentError())
            }
        }

        do {
            try process.run()
        } catch {
            DispatchQueue.main.async { self.fail("Could not start Python.", error.localizedDescription) }
            return
        }
        server = process

        let deadline = Date().addingTimeInterval(12)
        var address: String?
        while Date() < deadline {
            if let text = try? String(contentsOf: endpoint, encoding: .utf8) {
                let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
                if trimmed.hasPrefix("http://127.0.0.1:") {
                    address = trimmed
                    break
                }
            }
            if !process.isRunning { break }
            Thread.sleep(forTimeInterval: 0.05)
        }

        DispatchQueue.main.async {
            guard let address, let url = URL(string: address) else {
                self.fail("Stamp could not open the album.", self.recentError().isEmpty
                    ? "Python did not start listening. \(python) is what was tried."
                    : self.recentError())
                return
            }
            self.webView.load(URLRequest(url: url))
        }
    }

    private func recentError() -> String {
        errorLock.lock()
        let text = String(data: errorLog, encoding: .utf8) ?? ""
        errorLock.unlock()
        return text.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func fail(_ title: String, _ body: String) {
        if reportedFailure { return }
        reportedFailure = true
        let alert = NSAlert()
        alert.messageText = title
        alert.informativeText = body.isEmpty ? "Nothing more was reported." : body
        alert.alertStyle = .warning
        alert.runModal()
        NSApp.terminate(nil)
    }

    private func resourcesDirectory() -> URL? {
        let fm = FileManager.default
        var candidates: [URL] = []
        if let env = ProcessInfo.processInfo.environment["STAMP_RESOURCES"], !env.isEmpty {
            candidates.append(URL(fileURLWithPath: env, isDirectory: true))
        }
        if let res = Bundle.main.resourceURL {
            candidates.append(res)
        }
        candidates.append(Bundle.main.bundleURL.appendingPathComponent("Contents/Resources"))
        for url in candidates {
            if fm.fileExists(atPath: url.appendingPathComponent("stamp/gui/__init__.py").path) {
                return url
            }
        }
        return nil
    }

    private func findPython() -> String? {
        var candidates: [String] = []
        if let env = ProcessInfo.processInfo.environment["STAMP_PYTHON"], !env.isEmpty {
            candidates.append(env)
        }
        let names = ["python3.13", "python3.12", "python3.11", "python3"]
        for dir in ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"] {
            candidates.append(contentsOf: names.map { dir + "/" + $0 })
        }
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        for root in ["\(home)/Library/Frameworks/Python.framework/Versions", "/Library/Frameworks/Python.framework/Versions"] {
            if let versions = try? FileManager.default.contentsOfDirectory(atPath: root) {
                for version in versions.sorted().reversed() where version != "Current" {
                    candidates.append("\(root)/\(version)/bin/python3")
                }
            }
        }
        if let shim = ProcessInfo.processInfo.environment["HOME"].map({ $0 + "/.pyenv/shims/python3" }) {
            candidates.append(shim)
        }
        for path in candidates where pythonIsNewEnough(path) {
            return path
        }
        return nil
    }

    private func pythonIsNewEnough(_ path: String) -> Bool {
        guard FileManager.default.isExecutableFile(atPath: path) else { return false }
        let probe = Process()
        probe.executableURL = URL(fileURLWithPath: path)
        probe.arguments = ["-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"]
        probe.standardOutput = FileHandle.nullDevice
        probe.standardError = FileHandle.nullDevice
        do { try probe.run() } catch { return false }
        probe.waitUntilExit()
        return probe.terminationStatus == 0
    }
}

private extension NSMenu {
    func addItem(submenu: NSMenu) {
        let item = NSMenuItem()
        item.title = submenu.title
        item.submenu = submenu
        addItem(item)
    }
}

private extension NSMenu {
    @discardableResult
    func addItem(
        titled title: String,
        action: Selector,
        key: String,
        modifiers: NSEvent.ModifierFlags = [.command],
        target: AnyObject? = nil
    ) -> NSMenuItem {
        let item = addItem(withTitle: title, action: action, keyEquivalent: key)
        item.keyEquivalentModifierMask = key.isEmpty ? [] : modifiers
        item.target = target
        return item
    }
}
