import Cocoa
import WebKit
import Darwin

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, WKUIDelegate, WKNavigationDelegate {
    var window: NSWindow!
    var web: WKWebView!
    var server: Process?
    var quitting = false
    let port = 18765
    var site = ""
    var source = ""
    var python = ""
    var log = ""
    var base: URL { URL(string: "http://127.0.0.1:\(port)/")! }
    func click(_ id:String) { web?.evaluateJavaScript("document.getElementById('"+id+"')?.click()") }
    @objc func showAbout(){ click("about") }
    @objc func showSettings(){ click("settings") }
    @objc func newPost(){ click("new") }
    @objc func newPage(){ click("newPage") }
    @objc func saveDraft(){ click("save") }
    @objc func queueDraft(){ click("queue") }
    @objc func previewPage(){ click("preview") }
    @objc func reviewPublish(){ click("publish") }
    @objc func showPosts(){ click("postsNav") }
    @objc func showOpeners(){ click("openersNav") }
    @objc func showPages(){ click("pagesNav") }
    @objc func showImages(){ click("imagesNav") }
    @objc func showReader(){ click("readerNav") }
    @objc func showSaved(){ click("savedNav") }
    @objc func rebuildArchive(){ click("migrate") }
    @objc func showHelp(){ click("help") }
    func loadSettings() throws {
        let fallback=FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/Blynger/settings.json").path
        let path=ProcessInfo.processInfo.environment["BLYNGER_SETTINGS"] ?? fallback
        let data=try Data(contentsOf:URL(fileURLWithPath:path))
        guard let values=try JSONSerialization.jsonObject(with:data) as? [String:Any],
              let runtime=values["runtime"] as? [String:Any],
              let siteRoot=values["site_root"] as? String,
              let sourcePath=runtime["source"] as? String,
              let pythonPath=runtime["python"] as? String,
              let logPath=runtime["log"] as? String else { throw NSError(domain:"Blynger",code:1,userInfo:[NSLocalizedDescriptionKey:"The private settings file is incomplete."]) }
        site=siteRoot;source=sourcePath;python=pythonPath;log=logPath
    }
    func applicationDidFinishLaunching(_ notification: Notification) {
        do { try loadSettings() } catch { fail("Could not read Blynger’s private settings: \(error.localizedDescription)");return }
        if let icon=NSImage(contentsOfFile:source+"/native/blynger-logo.png") { NSApp.applicationIconImage=icon }
        let menu = NSMenu(); let appItem = NSMenuItem(); menu.addItem(appItem)
        let appMenu = NSMenu(); appItem.submenu = appMenu
        appMenu.addItem(withTitle: "About Blynger", action: #selector(showAbout), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Settings…", action: #selector(showSettings), keyEquivalent: ",")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Quit Blynger", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        let fileItem=NSMenuItem();menu.addItem(fileItem);let file=NSMenu(title:"File");fileItem.submenu=file
        file.addItem(withTitle:"New Post",action:#selector(newPost),keyEquivalent:"n")
        file.addItem(withTitle:"New Page…",action:#selector(newPage),keyEquivalent:"")
        file.addItem(.separator())
        file.addItem(withTitle:"Save Draft",action:#selector(saveDraft),keyEquivalent:"s")
        file.addItem(withTitle:"Queue for Publication",action:#selector(queueDraft),keyEquivalent:"")
        file.addItem(withTitle:"Preview",action:#selector(previewPage),keyEquivalent:"")
        file.addItem(.separator())
        file.addItem(withTitle:"Review & Publish…",action:#selector(reviewPublish),keyEquivalent:"")
        let editItem = NSMenuItem(); menu.addItem(editItem); let edit = NSMenu(title: "Edit"); editItem.submenu = edit
        for (title, action, key) in [("Undo", "undo:", "z"),("Cut", "cut:", "x"),("Copy", "copy:", "c"),("Paste", "paste:", "v"),("Select All", "selectAll:", "a")] { edit.addItem(withTitle: title, action: Selector(action), keyEquivalent: key) }
        let viewItem=NSMenuItem();menu.addItem(viewItem);let view=NSMenu(title:"View");viewItem.submenu=view
        for (title,action) in [("Posts",#selector(showPosts)),("Openers",#selector(showOpeners)),("Pages",#selector(showPages)),("Images",#selector(showImages)),("Reader",#selector(showReader)),("Saved",#selector(showSaved))] { view.addItem(withTitle:title,action:action,keyEquivalent:"") }
        let helpItem=NSMenuItem();menu.addItem(helpItem);let help=NSMenu(title:"Help");helpItem.submenu=help
        help.addItem(withTitle:"Blynger Help",action:#selector(showHelp),keyEquivalent:"?")
        help.addItem(.separator())
        help.addItem(withTitle:"Rebuild Blyg archive…",action:#selector(rebuildArchive),keyEquivalent:"")
        for item in appMenu.items where item.action != #selector(NSApplication.terminate(_:)) { item.target=self }
        for item in file.items+view.items+help.items { item.target=self }
        NSApp.mainMenu = menu
        window = NSWindow(contentRect: NSRect(x:0,y:0,width:1180,height:820), styleMask:[.titled,.closable,.miniaturizable,.resizable], backing:.buffered, defer:false)
        window.title = "Blynger"; window.delegate = self; window.center(); window.minSize = NSSize(width:720,height:500)
        web = WKWebView(frame: window.contentView!.bounds); web.autoresizingMask = [.width,.height]; web.uiDelegate = self; web.navigationDelegate = self
        window.contentView = web; window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps:true)
        web.loadHTMLString("<html><body style='background:#416b67;color:white;font:24px Georgia;padding:40px'>Starting Blynger…</body></html>", baseURL:nil)
        // Only retire an old launcher-owned Python server from this exact site.
        retireLegacyServer()
        let process = Process(); process.executableURL = URL(fileURLWithPath:python)
        process.arguments = ["-c", "import os,sys; os.getpgrp() == os.getpid() or os.setsid(); os.execv(sys.argv[1],sys.argv[1:])", python, source+"/app.py", "--no-browser", "--port", String(port)]
        process.currentDirectoryURL = URL(fileURLWithPath:source)
        if !FileManager.default.fileExists(atPath:log) { FileManager.default.createFile(atPath:log,contents:nil) }
        let handle = FileHandle(forWritingAtPath:log); handle?.seekToEndOfFile(); process.standardOutput = handle; process.standardError = handle
        do { try process.run(); server = process; waitForServer(60) } catch { fail("Could not start Blynger: \(error.localizedDescription)") }
    }
    func output(_ executable:String,_ args:[String]) -> String {
        let p=Process(); p.executableURL=URL(fileURLWithPath:executable);p.arguments=args;let pipe=Pipe();p.standardOutput=pipe;p.standardError=FileHandle.nullDevice
        do { try p.run();let data=pipe.fileHandleForReading.readDataToEndOfFile();p.waitUntilExit();return String(data:data,encoding:.utf8) ?? "" } catch { return "" }
    }
    func retireLegacyServer() {
        let ids=output("/usr/sbin/lsof",["-tiTCP:8765","-sTCP:LISTEN"]).split(separator:"\n")
        for id in ids {
            let command=output("/bin/ps",["-p",String(id),"-o","command="])
            let cwd=output("/usr/sbin/lsof",["-a","-p",String(id),"-d","cwd","-Fn"]).split(separator:"\n").first(where:{$0.hasPrefix("n")}).map{String($0.dropFirst())} ?? ""
            let ours=command.contains(source+"/app.py") || (command.contains("app.py") && cwd==source)
            if ours, let pid=Int32(id) { kill(pid,SIGINT) }
        }
    }
    func waitForServer(_ attempts:Int) {
        guard let process=server, process.isRunning else { fail("Blynger could not start. Check native-launcher.log in Library/Application Support/Blynger.");return }
        let request=URLRequest(url:base.appendingPathComponent("health"),cachePolicy:.reloadIgnoringLocalCacheData,timeoutInterval:1)
        URLSession.shared.dataTask(with:request) { data,response,error in
            DispatchQueue.main.async {
                guard !self.quitting else {return}
                if let data=data, let json=(try? JSONSerialization.jsonObject(with:data)) as? [String:Any], json["app"] as? String == "Blynger", self.server?.isRunning == true { self.web.load(URLRequest(url:self.base));return }
                if attempts<=0 {self.fail("Blynger did not finish starting.");return}
                DispatchQueue.main.asyncAfter(deadline:.now()+0.25){self.waitForServer(attempts-1)}
            }
        }.resume()
    }
    func fail(_ message:String){let alert=NSAlert();alert.messageText="Blynger needs attention";alert.informativeText=message;alert.runModal();NSApp.terminate(nil)}
    func windowShouldClose(_ sender:NSWindow)->Bool {NSApp.terminate(nil);return false}
    func applicationShouldTerminate(_ sender:NSApplication)->NSApplication.TerminateReply {
        if quitting {return .terminateNow}
        web.evaluateJavaScript("typeof dirty !== 'undefined' && dirty") { value,error in
            var leave=true
            if value as? Bool == true {let a=NSAlert();a.messageText="Quit without saving?";a.informativeText="Your unsaved edits will be lost. Saved drafts are kept.";a.addButton(withTitle:"Keep writing");a.addButton(withTitle:"Quit without saving");leave=a.runModal() == .alertSecondButtonReturn}
            self.quitting=leave;NSApp.reply(toApplicationShouldTerminate:leave)
        }
        return .terminateLater
    }
    func applicationWillTerminate(_ notification:Notification){if let p=server,p.isRunning {kill(-p.processIdentifier,SIGTERM);p.terminate()}}
    func webView(_ webView:WKWebView,decidePolicyFor action:WKNavigationAction,decisionHandler:@escaping(WKNavigationActionPolicy)->Void){
        if let url=action.request.url, url.scheme != "about", !(url.host=="127.0.0.1" && url.port==port) {if action.navigationType == .linkActivated {if ["https","http","mailto"].contains(url.scheme ?? "") {NSWorkspace.shared.open(url)}};decisionHandler(.cancel);return};decisionHandler(.allow)
    }
    func webView(_ webView:WKWebView,runOpenPanelWith parameters:WKOpenPanelParameters,initiatedByFrame frame:WKFrameInfo,completionHandler:@escaping([URL]?)->Void){let panel=NSOpenPanel();panel.canChooseDirectories=false;panel.allowsMultipleSelection=parameters.allowsMultipleSelection;panel.beginSheetModal(for:window){result in completionHandler(result == .OK ? panel.urls:nil)}}
    func webView(_ webView:WKWebView,runJavaScriptAlertPanelWithMessage message:String,initiatedByFrame frame:WKFrameInfo,completionHandler:@escaping()->Void){let a=NSAlert();a.messageText=message;a.runModal();completionHandler()}
    func webView(_ webView:WKWebView,runJavaScriptConfirmPanelWithMessage message:String,initiatedByFrame frame:WKFrameInfo,completionHandler:@escaping(Bool)->Void){let a=NSAlert();a.messageText=message;a.addButton(withTitle:"OK");a.addButton(withTitle:"Cancel");completionHandler(a.runModal() == .alertFirstButtonReturn)}
    func webView(_ webView:WKWebView,runJavaScriptTextInputPanelWithPrompt prompt:String,defaultText:String?,initiatedByFrame frame:WKFrameInfo,completionHandler:@escaping(String?)->Void){let a=NSAlert();a.messageText=prompt;let input=NSTextField(frame:NSRect(x:0,y:0,width:350,height:24));input.stringValue=defaultText ?? "";a.accessoryView=input;a.addButton(withTitle:"OK");a.addButton(withTitle:"Cancel");completionHandler(a.runModal() == .alertFirstButtonReturn ? input.stringValue:nil)}
}
let app=NSApplication.shared
app.setActivationPolicy(.regular)
let delegate=AppDelegate();app.delegate=delegate
app.run()
