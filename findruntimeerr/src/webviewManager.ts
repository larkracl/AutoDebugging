import * as vscode from "vscode";
import * as path from "path";
import * as fs from "fs";
// get...Results 함수들은 extension.ts의 전역 상태를 가져오는 함수입니다.
import {
  getAnalysisResults,
  getDynamicAnalysisResult,
  AnalysisResult,
} from "./extension";

export class WebviewManager {
  private static instance: WebviewManager;
  private staticAnalysisPanel: vscode.WebviewPanel | undefined;
  private dynamicAnalysisPanel: vscode.WebviewPanel | undefined;
  private readonly context: vscode.ExtensionContext;
  private lastActivePythonFileUri: vscode.Uri | undefined;

  private constructor(context: vscode.ExtensionContext) {
    this.context = context;
    // 활성화된 에디터가 바뀔 때 마지막 Python 파일을 추적하고, 열려있는 웹뷰를 업데이트합니다.
    vscode.window.onDidChangeActiveTextEditor((editor) => {
      if (editor && editor.document.languageId === "python") {
        this.lastActivePythonFileUri = editor.document.uri;
        this.updateAllWebviews();
      }
    });
  }

  public static getInstance(context: vscode.ExtensionContext): WebviewManager {
    if (!WebviewManager.instance) {
      WebviewManager.instance = new WebviewManager(context);
    }
    return WebviewManager.instance;
  }

  // --- 정적 분석 패널 관련 ---

  public createStaticAnalysisPanel(): void {
    if (this.staticAnalysisPanel) {
      this.staticAnalysisPanel.reveal(vscode.ViewColumn.Beside);
      return;
    }
    this.staticAnalysisPanel = this.createPanel(
      "staticAnalysis",
      "정적 분석",
      "static"
    );
    this.staticAnalysisPanel.onDidDispose(() => {
      this.staticAnalysisPanel = undefined;
    });

    // 패널이 다시 활성화될 때 데이터를 새로고침합니다.
    this.staticAnalysisPanel.onDidChangeViewState(() => {
      if (this.staticAnalysisPanel?.visible) {
        this.updateStaticWebview();
      }
    });

    // 생성 직후 데이터 로드
    this.updateStaticWebview();
  }

  public updateStaticWebview(): void {
    if (!this.staticAnalysisPanel) return;

    const currentUri = this.getCurrentUri();
    this.staticAnalysisPanel.webview.postMessage({
      command: "updateRealtimeErrors",
      errors: getAnalysisResults("realtime", currentUri),
    });
    this.staticAnalysisPanel.webview.postMessage({
      command: "updatePreciseErrors",
      errors: getAnalysisResults("precise", currentUri),
    });
    this.staticAnalysisPanel.webview.postMessage({
      command: "updateCurrentFile",
      filePath: currentUri?.fsPath,
    });
  }

  public updateRealtimeStatus(isEnable: boolean) {
    this.staticAnalysisPanel?.webview.postMessage({
      command: "updateRealtimeStatus",
      isEnable,
    });
  }

  // --- 동적 분석 패널 관련 ---

  public createDynamicAnalysisPanel(): void {
    if (this.dynamicAnalysisPanel) {
      this.dynamicAnalysisPanel.reveal(vscode.ViewColumn.Beside);
      return;
    }
    this.dynamicAnalysisPanel = this.createPanel(
      "dynamicAnalysis",
      "동적 분석",
      "dynamic"
    );
    this.dynamicAnalysisPanel.onDidDispose(() => {
      this.dynamicAnalysisPanel = undefined;
    });

    this.dynamicAnalysisPanel.onDidChangeViewState(() => {
      if (this.dynamicAnalysisPanel?.visible) {
        this.updateDynamicWebview();
      }
    });

    this.updateDynamicWebview();
  }

  public updateDynamicWebview(): void {
    if (!this.dynamicAnalysisPanel) return;
    const currentUri = this.getCurrentUri();
    if (currentUri) {
      const result = getDynamicAnalysisResult(currentUri);
      if (result) {
        this.updateDynamicAnalysisResult(result);
      }
      this.dynamicAnalysisPanel.webview.postMessage({
        command: "updateCurrentFile",
        filePath: currentUri.fsPath,
      });
    } else {
      this.dynamicAnalysisPanel.webview.postMessage({
        command: "updateCurrentFile",
        filePath: undefined,
      });
    }
  }

  public updateDynamicAnalysisProgress(
    step: number,
    status: "pending" | "active" | "completed" | "error",
    text: string
  ) {
    const overallText = `단계 ${step}/3: ${text}`;
    this.dynamicAnalysisPanel?.webview.postMessage({
      command: "updateDynamicAnalysisProgress",
      step,
      status,
      text,
      overallText,
    });
  }

  public updateDynamicAnalysisResult(result: AnalysisResult) {
    this.dynamicAnalysisPanel?.webview.postMessage({
      command: "updateDynamicAnalysisResult",
      ...result,
    });
  }

  public handleDynamicAnalysisError(step: number, text: string) {
    this.dynamicAnalysisPanel?.webview.postMessage({
      command: "dynamicAnalysisError",
      step,
      text,
    });
  }

  // --- 공통 헬퍼 함수 ---

  private createPanel(
    viewType: string,
    title: string,
    htmlType: "static" | "dynamic"
  ): vscode.WebviewPanel {
    const panel = vscode.window.createWebviewPanel(
      viewType,
      title,
      vscode.ViewColumn.Beside,
      {
        enableScripts: true,
        retainContextWhenHidden: true,
        localResourceRoots: [
          vscode.Uri.file(
            path.join(this.context.extensionPath, "src", "webview")
          ),
        ],
      }
    );
    panel.webview.html = this.getWebviewHtml(htmlType, panel.webview);
    panel.webview.onDidReceiveMessage((message) => this.handleMessage(message));
    return panel;
  }

  private getWebviewHtml(
    viewType: "static" | "dynamic",
    webview: vscode.Webview
  ): string {
    const webviewDir = path.join(this.context.extensionPath, "src", "webview");
    const htmlPath = path.join(webviewDir, `${viewType}.html`);
    let htmlContent = fs.readFileSync(htmlPath, "utf8");

    const toUri = (filePath: string) =>
      webview.asWebviewUri(vscode.Uri.file(path.join(webviewDir, filePath)));

    // 정규식을 사용하여 모든 플레이스홀더를 한 번에 교체
    htmlContent = htmlContent
      .replace(/\$\{styleUri\}/g, toUri("style.css").toString())
      .replace(/\$\{scriptUri\}/g, toUri(`${viewType}.js`).toString());

    return htmlContent;
  }

  private async handleMessage(message: any): Promise<void> {
    // 웹뷰로부터 받은 모든 메시지는 extension.ts에 등록된 커맨드를 호출하는 방식으로 처리
    switch (message.command) {
      // Static Panel Commands
      case "runPreciseAnalysis":
        this.staticAnalysisPanel?.webview.postMessage({
          command: "updatePreciseStatus",
          status: "분석 중...",
        });
        await vscode.commands.executeCommand(
          "findRuntimeErr.analyzeCurrentFile"
        );
        this.staticAnalysisPanel?.webview.postMessage({
          command: "updatePreciseStatus",
          status: "완료됨",
        });
        break;
      case "toggleRealtimeAnalysis":
        await vscode.commands.executeCommand(
          "findRuntimeErr.toggleRealtimeAnalysis"
        );
        break;
      case "getRealtimeStatus":
        await vscode.commands.executeCommand(
          "findRuntimeErr.sendRealtimeStatus"
        );
        break;
      case "getRealtimeErrors":
      case "getPreciseErrors":
        this.updateStaticWebview();
        break;

      // Dynamic Panel Commands
      case "runDynamicAnalysis":
        await vscode.commands.executeCommand(
          "findRuntimeErr.runDynamicAnalysis"
        );
        break;
      case "killDynamicAnalysis":
        await vscode.commands.executeCommand(
          "findRuntimeErr.killPythonProcess"
        );
        break;

      // Common Commands
      case "getCurrentFile":
        this.updateAllWebviews();
        break;
      case "goToError":
        this.goToError(message.line, message.column, message.filePath);
        break;
    }
  }

  private updateAllWebviews() {
    this.updateStaticWebview();
    this.updateDynamicWebview();
  }

  private getCurrentUri(): vscode.Uri | undefined {
    return vscode.window.activeTextEditor?.document.languageId === "python"
      ? vscode.window.activeTextEditor.document.uri
      : this.lastActivePythonFileUri;
  }

  private updateCurrentFileInWebview(panelType: "static" | "dynamic") {
    const panel =
      panelType === "static"
        ? this.staticAnalysisPanel
        : this.dynamicAnalysisPanel;
    const currentUri = this.getCurrentUri();
    panel?.webview.postMessage({
      command: "updateCurrentFile",
      filePath: currentUri?.fsPath,
    });
  }

  private async goToError(
    line: number,
    column: number,
    filePath?: string
  ): Promise<void> {
    const targetPath = filePath || this.getCurrentUri()?.fsPath;
    if (!targetPath) {
      vscode.window.showWarningMessage(
        "오류 위치로 이동할 파일을 찾을 수 없습니다."
      );
      return;
    }
    try {
      const uri = vscode.Uri.file(targetPath);
      const editor = await vscode.window.showTextDocument(uri, {
        viewColumn: vscode.ViewColumn.One,
        preview: false,
      });
      const position = new vscode.Position(
        Math.max(0, line - 1),
        Math.max(0, column)
      );
      editor.selection = new vscode.Selection(position, position);
      editor.revealRange(
        new vscode.Range(position, position),
        vscode.TextEditorRevealType.InCenter
      );
    } catch (error: any) {
      vscode.window.showErrorMessage(
        `파일 이동 중 오류 발생: ${error.message}`
      );
    }
  }
}
