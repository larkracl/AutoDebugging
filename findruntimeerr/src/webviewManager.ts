import * as vscode from 'vscode';
import * as path from 'path';
import { execSync } from 'child_process';
import { getRealtimeAnalysisResults, getPreciseAnalysisResults, getDynamicAnalysisResults } from './extension';

export class WebviewManager {
  private static instance: WebviewManager;
  private staticAnalysisPanel: vscode.WebviewPanel | undefined;
  private dynamicAnalysisPanel: vscode.WebviewPanel | undefined;
  private context: vscode.ExtensionContext | undefined;
  private lastSelectedPythonFile: string | undefined; // 마지막으로 선택된 Python 파일 경로

  private constructor() {}

  public static getInstance(): WebviewManager {
    if (!WebviewManager.instance) {
      WebviewManager.instance = new WebviewManager();
    }
    return WebviewManager.instance;
  }

  public createStaticAnalysisPanel(context: vscode.ExtensionContext): void {
    if (this.staticAnalysisPanel) {
      this.staticAnalysisPanel.reveal();
      return;
    }

    this.context = context;

    this.staticAnalysisPanel = vscode.window.createWebviewPanel(
      'staticAnalysis',
      '정적 분석',
      vscode.ViewColumn.One,
      {
        enableScripts: true,
        retainContextWhenHidden: true,
        localResourceRoots: [
          vscode.Uri.file(path.join(context.extensionPath, 'src', 'webview'))
        ]
      }
    );

    this.staticAnalysisPanel.webview.html = this.getStaticAnalysisHtml();

    // 웹뷰 메시지 핸들러 등록
    this.staticAnalysisPanel.webview.onDidReceiveMessage(
      async (message) => {
        await this.handleStaticAnalysisMessage(message);
      }
    );

    // 현재 파일 정보 초기화
    this.updateStaticAnalysisFileInfo();

    // 파일 변경 시 파일 정보 업데이트
    const fileChangeDisposable = vscode.window.onDidChangeActiveTextEditor(() => {
      this.updateStaticAnalysisFileInfo();
    });

    this.staticAnalysisPanel.onDidDispose(() => {
      this.staticAnalysisPanel = undefined;
      fileChangeDisposable.dispose();
    });
  }

  public createDynamicAnalysisPanel(context: vscode.ExtensionContext): void {
    if (this.dynamicAnalysisPanel) {
      this.dynamicAnalysisPanel.reveal();
      return;
    }

    this.dynamicAnalysisPanel = vscode.window.createWebviewPanel(
      'dynamicAnalysis',
      '동적 분석',
      vscode.ViewColumn.Two,
      {
        enableScripts: true,
        retainContextWhenHidden: true,
        localResourceRoots: [
          vscode.Uri.file(path.join(context.extensionPath, 'src', 'webview'))
        ]
      }
    );

    this.dynamicAnalysisPanel.webview.html = this.getDynamicAnalysisHtml();

    // 웹뷰 메시지 핸들러 등록
    this.dynamicAnalysisPanel.webview.onDidReceiveMessage(
      async (message) => {
        await this.handleDynamicAnalysisMessage(message);
      }
    );

    // 현재 파일 정보 업데이트
    this.updateCurrentFileInfo();

    // 파일 변경 시 파일 정보 업데이트
    const fileChangeDisposable = vscode.window.onDidChangeActiveTextEditor(() => {
      this.updateCurrentFileInfo();
    });

    this.dynamicAnalysisPanel.onDidDispose(() => {
      this.dynamicAnalysisPanel = undefined;
      fileChangeDisposable.dispose();
    });
  }

  private getStaticAnalysisHtml(): string {
    return `
      <!DOCTYPE html>
      <html lang="ko">
      <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>정적 분석</title>
        <style>
          body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: var(--vscode-editor-background);
            color: var(--vscode-editor-foreground);
          }
          .container {
            max-width: 1000px;
            margin: 0 auto;
          }
          h1 {
            color: var(--vscode-editor-foreground);
            border-bottom: 1px solid var(--vscode-panel-border);
            padding-bottom: 10px;
            margin-bottom: 20px;
          }
          
          /* 탭 스타일 */
          .tab-container {
            border-bottom: 1px solid var(--vscode-panel-border);
            margin-bottom: 20px;
          }
          .tab-buttons {
            display: flex;
            gap: 0;
          }
          .tab-button {
            background-color: var(--vscode-editor-inactiveSelectionBackground);
            color: var(--vscode-editor-foreground);
            border: 1px solid var(--vscode-panel-border);
            border-bottom: none;
            padding: 12px 24px;
            cursor: pointer;
            font-size: 14px;
            transition: all 0.2s;
          }
          .tab-button:first-child {
            border-top-left-radius: 6px;
          }
          .tab-button:last-child {
            border-top-right-radius: 6px;
          }
          .tab-button.active {
            background-color: var(--vscode-editor-background);
            color: var(--vscode-editor-foreground);
            border-bottom: 1px solid var(--vscode-editor-background);
            margin-bottom: -1px;
          }
          .tab-button:hover:not(.active) {
            background-color: var(--vscode-list-hoverBackground);
          }
          
          .tab-content {
            display: none;
            padding: 20px;
            background-color: var(--vscode-editor-background);
            border: 1px solid var(--vscode-panel-border);
            border-top: none;
            border-radius: 0 0 6px 6px;
          }
          .tab-content.active {
            display: block;
          }
          
          .analysis-section {
            background-color: var(--vscode-editor-inactiveSelectionBackground);
            border: 1px solid var(--vscode-panel-border);
            border-radius: 6px;
            padding: 20px;
            margin: 20px 0;
          }
          .button {
            background-color: var(--vscode-button-background);
            color: var(--vscode-button-foreground);
            border: none;
            padding: 10px 20px;
            border-radius: 4px;
            cursor: pointer;
            margin: 5px;
            font-size: 14px;
          }
          .button:hover {
            background-color: var(--vscode-button-hoverBackground);
          }
          .button:disabled {
            background-color: var(--vscode-button-secondaryBackground);
            cursor: not-allowed;
          }
          .status {
            margin-top: 20px;
            padding: 10px;
            border-radius: 4px;
            background-color: var(--vscode-notifications-background);
            font-size: 14px;
          }
          
          /* 오류 목록 스타일 */
          .error-list {
            margin-top: 20px;
          }
          .error-item {
            background-color: var(--vscode-editor-inactiveSelectionBackground);
            border: 1px solid var(--vscode-panel-border);
            border-radius: 6px;
            padding: 15px;
            margin: 10px 0;
            cursor: pointer;
            transition: all 0.2s;
          }
          .error-item:hover {
            background-color: var(--vscode-list-hoverBackground);
          }
          .error-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 8px;
          }
          .error-type {
            background-color: var(--vscode-errorForeground);
            color: var(--vscode-editor-background);
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: bold;
          }
          .error-location {
            color: var(--vscode-descriptionForeground);
            font-size: 12px;
          }
          .error-message {
            color: var(--vscode-editor-foreground);
            font-size: 14px;
            line-height: 1.4;
          }
          .no-errors {
            text-align: center;
            color: var(--vscode-descriptionForeground);
            padding: 40px;
            font-style: italic;
          }
          
          /* 파일 정보 스타일 */
          .file-info {
            background-color: var(--vscode-editor-inactiveSelectionBackground);
            border: 1px solid var(--vscode-panel-border);
            border-radius: 6px;
            padding: 15px;
            margin-bottom: 20px;
            display: flex;
            align-items: center;
            gap: 10px;
          }
          .file-label {
            font-weight: bold;
            color: var(--vscode-editor-foreground);
            font-size: 14px;
            white-space: nowrap;
          }
          .file-path {
            color: var(--vscode-textPreformat-foreground);
            font-family: 'Courier New', monospace;
            font-size: 13px;
            word-break: break-all;
            flex: 1;
          }
          .file-path.no-file {
            color: var(--vscode-descriptionForeground);
            font-style: italic;
          }
        </style>
      </head>
      <body>
        <div class="container">
          <h1>정적 분석</h1>
          
          <!-- 현재 파일 정보 표시 -->
          <div class="file-info" id="fileInfo">
            <div class="file-label">현재 수정 중인 파일:</div>
            <div class="file-path" id="currentFilePath">파일을 선택해주세요</div>
          </div>
          
          <!-- 탭 컨테이너 -->
          <div class="tab-container">
            <div class="tab-buttons">
              <button class="tab-button active" onclick="switchTab('realtime')">실시간 분석</button>
              <button class="tab-button" onclick="switchTab('precise')">정밀 분석</button>
            </div>
          </div>
          
          <!-- 실시간 분석 탭 -->
          <div id="realtime-tab" class="tab-content active">
            <div class="analysis-section">
              <h3>실시간 분석 설정</h3>
              <p>파일 저장이나 수정 시 자동으로 실행되는 분석입니다.</p>
              <button class="button" onclick="toggleRealtimeAnalysis()">실시간 분석 토글</button>
              <div id="realtimeStatus" class="status">상태: 활성화됨</div>
            </div>
            
            <div class="analysis-section">
              <h3>실시간 분석 결과</h3>
              <button class="button" onclick="refreshRealtimeErrors()">새로고침</button>
              <div id="realtimeErrorList" class="error-list">
                <div class="no-errors">실시간 분석 결과가 없습니다.</div>
              </div>
            </div>
          </div>
          
          <!-- 정밀 분석 탭 -->
          <div id="precise-tab" class="tab-content">
            <div class="analysis-section">
              <h3>정밀 분석 실행</h3>
              <p>사용자가 명령어를 통해 직접 실행하는 상세 분석입니다.</p>
              <button class="button" onclick="runPreciseAnalysis()">정밀 분석 실행</button>
              <div id="preciseStatus" class="status">상태: 대기 중</div>
            </div>
            
            <div class="analysis-section">
              <h3>정밀 분석 결과</h3>
              <button class="button" onclick="refreshPreciseErrors()">새로고침</button>
              <div id="preciseErrorList" class="error-list">
                <div class="no-errors">정밀 분석 결과가 없습니다.</div>
              </div>
            </div>
          </div>
        </div>

        <script>
          const vscode = acquireVsCodeApi();
          let currentTab = 'realtime';

          function switchTab(tabName) {
            // 탭 버튼 상태 변경
            document.querySelectorAll('.tab-button').forEach(btn => {
              btn.classList.remove('active');
            });
            document.querySelector(\`[onclick="switchTab('\${tabName}')"]\`).classList.add('active');
            
            // 탭 콘텐츠 상태 변경
            document.querySelectorAll('.tab-content').forEach(content => {
              content.classList.remove('active');
            });
            document.getElementById(\`\${tabName}-tab\`).classList.add('active');
            
            currentTab = tabName;
            
            // 탭 전환 시 해당 데이터 로드
            if (tabName === 'realtime') {
              refreshRealtimeErrors();
            } else if (tabName === 'precise') {
              refreshPreciseErrors();
            }
          }

          function toggleRealtimeAnalysis() {
            vscode.postMessage({
              command: 'toggleRealtimeAnalysis'
            });
          }

          function runPreciseAnalysis() {
            vscode.postMessage({
              command: 'runPreciseAnalysis'
            });
          }

          function refreshRealtimeErrors() {
            vscode.postMessage({
              command: 'getRealtimeErrors'
            });
          }

          function refreshPreciseErrors() {
            vscode.postMessage({
              command: 'getPreciseErrors'
            });
          }

          function renderErrorList(containerId, errors) {
            const container = document.getElementById(containerId);
            
            if (!errors || errors.length === 0) {
              container.innerHTML = '<div class="no-errors">분석 결과가 없습니다.</div>';
              return;
            }
            
            const errorHtml = errors.map(error => \`
              <div class="error-item" onclick="goToError(\${error.line || 1}, \${error.column || 0}, '\${error.filePath || ''}')">
                <div class="error-header">
                  <span class="error-type">\${error.errorType || 'Error'}</span>
                  <span class="error-location">줄 \${error.line || 'N/A'}, 열 \${error.column || 'N/A'}</span>
                </div>
                <div class="error-message">\${error.message}</div>
                \${error.memoryUsage ? \`<div class="error-memory">메모리 사용량: \${error.memoryUsage} bytes</div>\` : ''}
              </div>
            \`).join('');
            
            container.innerHTML = errorHtml;
          }

          function goToError(line, column, filePath) {
            vscode.postMessage({
              command: 'goToError',
              line: line,
              column: column,
              filePath: filePath
            });
          }

          function updateCurrentFile(filePath) {
            const filePathElement = document.getElementById('currentFilePath');
            if (filePath) {
              // 파일 경로에서 파일명만 추출하여 표시
              const fileName = filePath.split(/[\\/]/).pop();
              filePathElement.textContent = fileName + ' (' + filePath + ')';
              filePathElement.className = 'file-path';
            } else {
              filePathElement.textContent = '파일을 선택해주세요';
              filePathElement.className = 'file-path no-file';
            }
          }

          // 메시지 수신 처리
          window.addEventListener('message', event => {
            const message = event.data;
            switch (message.command) {
              case 'updateRealtimeStatus':
                document.getElementById('realtimeStatus').textContent = '상태: ' + message.status;
                break;
              case 'updatePreciseStatus':
                document.getElementById('preciseStatus').textContent = '상태: ' + message.status;
                break;
              case 'updateRealtimeErrors':
                renderErrorList('realtimeErrorList', message.errors);
                break;
              case 'updatePreciseErrors':
                renderErrorList('preciseErrorList', message.errors);
                break;
              case 'updateCurrentFile':
                updateCurrentFile(message.filePath);
                break;
            }
          });

          // 초기 로드
          window.addEventListener('load', () => {
            refreshRealtimeErrors();
          });
        </script>
      </body>
      </html>
    `;
  }

  private getDynamicAnalysisHtml(): string {
    return `
      <!DOCTYPE html>
      <html lang="ko">
      <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>동적 분석</title>
        <style>
          body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: var(--vscode-editor-background);
            color: var(--vscode-editor-foreground);
          }
          .container {
            max-width: 1000px;
            margin: 0 auto;
          }
          h1 {
            color: var(--vscode-editor-foreground);
            border-bottom: 1px solid var(--vscode-panel-border);
            padding-bottom: 10px;
            margin-bottom: 20px;
          }
          
          /* 탭 스타일 */
          .tab-container {
            border-bottom: 1px solid var(--vscode-panel-border);
            margin-bottom: 20px;
          }
          .tab-buttons {
            display: flex;
            gap: 0;
          }
          .tab-button {
            background-color: var(--vscode-editor-inactiveSelectionBackground);
            color: var(--vscode-editor-foreground);
            border: 1px solid var(--vscode-panel-border);
            border-bottom: none;
            padding: 12px 24px;
            cursor: pointer;
            font-size: 14px;
            transition: all 0.2s;
          }
          .tab-button:first-child {
            border-top-left-radius: 6px;
          }
          .tab-button:last-child {
            border-top-right-radius: 6px;
          }
          .tab-button.active {
            background-color: var(--vscode-editor-background);
            color: var(--vscode-editor-foreground);
            border-bottom: 1px solid var(--vscode-editor-background);
            margin-bottom: -1px;
          }
          .tab-button:hover:not(.active) {
            background-color: var(--vscode-list-hoverBackground);
          }
          
          .tab-content {
            display: none;
            padding: 20px;
            background-color: var(--vscode-editor-background);
            border: 1px solid var(--vscode-panel-border);
            border-top: none;
            border-radius: 0 0 6px 6px;
          }
          .tab-content.active {
            display: block;
          }
          
          .analysis-section {
            background-color: var(--vscode-editor-inactiveSelectionBackground);
            border: 1px solid var(--vscode-panel-border);
            border-radius: 6px;
            padding: 20px;
            margin: 20px 0;
          }
          .button {
            background-color: var(--vscode-button-background);
            color: var(--vscode-button-foreground);
            border: none;
            padding: 10px 20px;
            border-radius: 4px;
            cursor: pointer;
            margin: 5px;
            font-size: 14px;
          }
          .button:hover {
            background-color: var(--vscode-button-hoverBackground);
          }
          .button:disabled {
            background-color: var(--vscode-button-secondaryBackground);
            cursor: not-allowed;
          }
          .status {
            margin-top: 20px;
            padding: 10px;
            border-radius: 4px;
            background-color: var(--vscode-notifications-background);
            font-size: 14px;
          }
          .input-group {
            margin: 15px 0;
          }
          .input-label {
            display: block;
            margin-bottom: 5px;
            font-weight: bold;
            color: var(--vscode-editor-foreground);
          }
          .input-field {
            width: 200px;
            padding: 8px;
            border: 1px solid var(--vscode-input-border);
            border-radius: 4px;
            background-color: var(--vscode-input-background);
            color: var(--vscode-input-foreground);
            font-size: 14px;
          }
          .input-field:focus {
            outline: none;
            border-color: var(--vscode-focusBorder);
          }
          
          /* 테스트 결과 스타일 */
          .test-result {
            background-color: var(--vscode-editor-inactiveSelectionBackground);
            border: 1px solid var(--vscode-panel-border);
            border-radius: 6px;
            padding: 15px;
            margin: 10px 0;
          }
          .function-name {
            font-weight: bold;
            color: var(--vscode-editor-foreground);
            margin-bottom: 10px;
            font-size: 16px;
          }
          .test-case {
            background-color: var(--vscode-editor-background);
            border: 1px solid var(--vscode-panel-border);
            border-radius: 4px;
            padding: 10px;
            margin: 5px 0;
          }
          .test-input {
            color: var(--vscode-descriptionForeground);
            font-size: 12px;
            margin-bottom: 5px;
          }
          .test-expected {
            color: var(--vscode-textPreformat-foreground);
            font-family: 'Courier New', monospace;
            font-size: 12px;
            margin-bottom: 5px;
          }
          .test-actual {
            color: var(--vscode-textPreformat-foreground);
            font-family: 'Courier New', monospace;
            font-size: 12px;
          }
          .test-success {
            border-left: 3px solid var(--vscode-testing-iconPassed);
          }
          .test-failure {
            border-left: 3px solid var(--vscode-testing-iconFailed);
          }
          
          /* 오류 목록 스타일 */
          .error-list {
            margin-top: 20px;
          }
          .error-item {
            background-color: var(--vscode-editor-inactiveSelectionBackground);
            border: 1px solid var(--vscode-panel-border);
            border-radius: 6px;
            padding: 15px;
            margin: 10px 0;
            cursor: pointer;
            transition: all 0.2s;
          }
          .error-item:hover {
            background-color: var(--vscode-list-hoverBackground);
          }
          .error-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 8px;
          }
          .error-type {
            background-color: var(--vscode-errorForeground);
            color: var(--vscode-editor-background);
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: bold;
          }
          .error-memory {
            background-color: var(--vscode-warningForeground);
            color: var(--vscode-editor-background);
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: bold;
          }
          .error-message {
            color: var(--vscode-editor-foreground);
            font-size: 14px;
            line-height: 1.4;
          }
          .no-errors {
            text-align: center;
            color: var(--vscode-descriptionForeground);
            padding: 40px;
            font-style: italic;
          }
          .no-tests {
            text-align: center;
            color: var(--vscode-descriptionForeground);
            padding: 40px;
            font-style: italic;
          }
          /* 진행 상황 표시 스타일 */
          .progress-container {
            margin: 20px 0;
            display: none;
          }
          .progress-bar {
            width: 100%;
            height: 20px;
            background-color: var(--vscode-progressBar-background);
            border-radius: 10px;
            overflow: hidden;
            margin-bottom: 10px;
          }
          .progress-fill {
            height: 100%;
            background-color: var(--vscode-progressBar-foreground);
            width: 0%;
            transition: width 0.3s ease;
          }
          .progress-text {
            text-align: center;
            color: var(--vscode-editor-foreground);
            font-size: 14px;
            margin-bottom: 10px;
          }
          .step-list {
            list-style: none;
            padding: 0;
            margin: 0;
          }
          .step-item {
            padding: 8px 12px;
            margin: 5px 0;
            border-radius: 4px;
            font-size: 13px;
            display: flex;
            align-items: center;
          }
          .step-item.pending {
            background-color: var(--vscode-editor-inactiveSelectionBackground);
            color: var(--vscode-descriptionForeground);
          }
          .step-item.active {
            background-color: var(--vscode-progressBar-background);
            color: var(--vscode-editor-foreground);
            font-weight: bold;
          }
          .step-item.completed {
            background-color: var(--vscode-testing-iconPassed);
            color: var(--vscode-editor-background);
          }
          .step-item.error {
            background-color: var(--vscode-testing-iconFailed);
            color: var(--vscode-editor-background);
          }
          .step-icon {
            margin-right: 8px;
            font-size: 16px;
          }
          
          /* 파일 정보 스타일 */
          .file-info {
            background-color: var(--vscode-editor-inactiveSelectionBackground);
            border: 1px solid var(--vscode-panel-border);
            border-radius: 6px;
            padding: 15px;
            margin-bottom: 20px;
            display: flex;
            align-items: center;
            gap: 10px;
          }
          .file-label {
            font-weight: bold;
            color: var(--vscode-editor-foreground);
            font-size: 14px;
            white-space: nowrap;
          }
          .file-path {
            color: var(--vscode-textPreformat-foreground);
            font-family: 'Courier New', monospace;
            font-size: 13px;
            word-break: break-all;
            flex: 1;
          }
          .file-path.no-file {
            color: var(--vscode-descriptionForeground);
            font-style: italic;
          }
        </style>
      </head>
      <body>
        <div class="container">
          <h1>동적 분석</h1>
          
          <!-- 현재 파일 정보 표시 -->
          <div class="file-info" id="fileInfo">
            <div class="file-label">현재 수정 중인 파일:</div>
            <div class="file-path" id="currentFilePath">파일을 선택해주세요</div>
          </div>
          
          <!-- 탭 컨테이너 -->
          <div class="tab-container">
            <div class="tab-buttons">
              <button class="tab-button active" onclick="switchTab('ai')">AI 테스트케이스 생성</button>
              <button class="tab-button" onclick="switchTab('manual')">수동 테스트케이스 생성</button>
            </div>
          </div>
          
          <!-- AI 테스트케이스 생성 탭 -->
          <div id="ai-tab" class="tab-content active">
            <div class="analysis-section">
              <h3>AI 테스트케이스 생성 설정</h3>
              <div class="input-group">
                <label class="input-label" for="memoryLimit">메모리 허용치 (바이트):</label>
                <input type="number" id="memoryLimit" class="input-field" value="1048576" min="1024" max="1073741824">
                <button class="button" onclick="setMemoryLimit()">설정</button>
              </div>
              <button class="button" onclick="generateAITests()" id="generateButton">AI 테스트케이스 생성</button>
              <div id="aiTestStatus" class="status">상태: 대기 중</div>
            </div>
            
            <!-- 진행 상황 표시 영역 -->
            <div id="progressContainer" class="progress-container">
              <div class="progress-text" id="progressText">분석 진행 중...</div>
              <div class="progress-bar">
                <div class="progress-fill" id="progressFill"></div>
              </div>
              <ul class="step-list" id="stepList">
                <li class="step-item pending" id="step1">
                  <span class="step-icon">⏳</span>
                  <span>AI 테스트케이스 생성 중...</span>
                </li>
                <li class="step-item pending" id="step2">
                  <span class="step-icon">⏳</span>
                  <span>함수 테스트 실행 중...</span>
                </li>
              </ul>
            </div>
            
            <div class="analysis-section">
              <h3>AI 테스트케이스 결과</h3>
              <div id="testResults">
                <div class="no-tests">AI 테스트케이스 결과가 여기에 표시됩니다.</div>
              </div>
            </div>
            
            <div class="analysis-section">
              <h3>발견된 오류</h3>
              <div id="errorList">
                <div class="no-errors">오류가 없습니다.</div>
              </div>
            </div>
          </div>
          
          <!-- 수동 테스트케이스 생성 탭 -->
          <div id="manual-tab" class="tab-content">
            <div class="analysis-section">
              <h3>수동 테스트케이스 생성</h3>
              <p>이 기능은 아직 구현되지 않았습니다.</p>
              <div class="no-tests">수동 테스트케이스 생성 기능이 곧 추가될 예정입니다.</div>
            </div>
          </div>
        </div>

        <script>
          const vscode = acquireVsCodeApi();
          let currentTab = 'ai';
          let memoryLimit = 1048576; // 기본값: 1MB

          function switchTab(tabName) {
            // 탭 버튼 상태 변경
            document.querySelectorAll('.tab-button').forEach(btn => {
              btn.classList.remove('active');
            });
            document.querySelector(\`[onclick="switchTab('\${tabName}')"]\`).classList.add('active');
            
            // 탭 콘텐츠 상태 변경
            document.querySelectorAll('.tab-content').forEach(content => {
              content.classList.remove('active');
            });
            document.getElementById(\`\${tabName}-tab\`).classList.add('active');
            
            currentTab = tabName;
          }

          function setMemoryLimit() {
            const input = document.getElementById('memoryLimit');
            const value = parseInt(input.value);
            if (value >= 1024 && value <= 1073741824) {
              memoryLimit = value;
              vscode.window.showInformationMessage(\`메모리 허용치가 \${value} 바이트로 설정되었습니다.\`);
            } else {
              vscode.window.showErrorMessage('메모리 허용치는 1KB ~ 1GB 사이여야 합니다.');
            }
          }

          function generateAITests() {
            // 버튼 비활성화
            const button = document.getElementById('generateButton');
            button.disabled = true;
            button.textContent = '분석 중...';
            
            // 진행 상황 표시 시작
            showProgress();
            
            vscode.postMessage({
              command: 'generateAITests',
              memoryLimit: memoryLimit
            });
          }

          function showProgress() {
            document.getElementById('progressContainer').style.display = 'block';
            document.getElementById('progressFill').style.width = '0%';
            document.getElementById('progressText').textContent = '분석 준비 중...';
            
            // 모든 단계를 pending으로 초기화
            for (let i = 1; i <= 2; i++) {
              const step = document.getElementById(\`step\${i}\`);
              step.className = 'step-item pending';
              step.querySelector('.step-icon').textContent = '⏳';
            }
          }

          function hideProgress() {
            // 진행 상황 표시는 그대로 두고 버튼만 다시 활성화
            const button = document.getElementById('generateButton');
            button.disabled = false;
            button.textContent = 'AI 테스트케이스 생성';
            
            // 상태 메시지 업데이트
            document.getElementById('aiTestStatus').textContent = '상태: 완료됨';
          }

          function updateStep(stepNumber, status, text) {
            const step = document.getElementById(\`step\${stepNumber}\`);
            if (!step) return;
            
            step.className = \`step-item \${status}\`;
            step.querySelector('span:last-child').textContent = text;
            
            let icon = '⏳';
            if (status === 'active') icon = '🔄';
            else if (status === 'completed') icon = '✅';
            else if (status === 'error') icon = '❌';
            
            step.querySelector('.step-icon').textContent = icon;
            
            // 진행률 업데이트
            const progress = (stepNumber / 2) * 100;
            document.getElementById('progressFill').style.width = \`\${progress}%\`;
          }

          function updateProgressText(text) {
            document.getElementById('progressText').textContent = text;
          }

          function updateCurrentFile(filePath) {
            const filePathElement = document.getElementById('currentFilePath');
            if (filePath) {
              // 파일 경로에서 파일명만 추출하여 표시
              const fileName = filePath.split(/[\\/]/).pop();
              filePathElement.textContent = fileName + ' (' + filePath + ')';
              filePathElement.className = 'file-path';
            } else {
              filePathElement.textContent = '파일을 선택해주세요';
              filePathElement.className = 'file-path no-file';
            }
          }

          function resetButtonState() {
            const button = document.getElementById('generateButton');
            button.disabled = false;
            button.textContent = 'AI 테스트케이스 생성';
          }

          function renderTestResults(results) {
            const container = document.getElementById('testResults');
            
            if (!results || results.length === 0) {
              container.innerHTML = '<div class="no-tests">테스트 결과가 없습니다.</div>';
              return;
            }
            
            const resultsHtml = results.map(result => \`
              <div class="test-result">
                <div class="function-name">\${result.functionName}</div>
                \${result.testCases.map(testCase => \`
                  <div class="test-case \${testCase.success ? 'test-success' : 'test-failure'}">
                    <div class="test-input">입력: \${testCase.input}</div>
                    <div class="test-expected">예상값: \${testCase.expected}</div>
                    <div class="test-actual">실제값: \${testCase.actual}</div>
                  </div>
                \`).join('')}
              </div>
            \`).join('');
            
            container.innerHTML = resultsHtml;
          }

          function renderErrorList(errors) {
            const container = document.getElementById('errorList');
            
            if (!errors || errors.length === 0) {
              container.innerHTML = '<div class="no-errors">오류가 없습니다.</div>';
              return;
            }
            
            const errorHtml = errors.map((error, index) => \`
              <div class="error-item" onclick="goToError(\${error.line || 1}, \${error.column || 0}, '\${error.filePath || ''}')">
                <div class="error-header">
                  <span class="error-type">\${error.errorType || 'Error'}</span>
                  <span class="error-location">줄 \${error.line || 'N/A'}, 열 \${error.column || 'N/A'}</span>
                </div>
                <div class="error-message">\${error.message}</div>
                \${error.memoryUsage ? \`<div class="error-memory">메모리 사용량: \${error.memoryUsage} bytes</div>\` : ''}
              </div>
            \`).join('');
            
            container.innerHTML = errorHtml;
          }

          function goToError(line, column, filePath) {
            vscode.postMessage({
              command: 'goToError',
              line: line,
              column: column,
              filePath: filePath
            });
          }

          // 메시지 수신 처리
          window.addEventListener('message', event => {
            const message = event.data;
            switch (message.command) {
              case 'updateAITestStatus':
                document.getElementById('aiTestStatus').textContent = '상태: ' + message.status;
                break;
              case 'updateUserTestStatus':
                document.getElementById('userTestStatus').textContent = '상태: ' + message.status;
                break;
              case 'updateTestResults':
                renderTestResults(message.results);
                break;
              case 'updateErrorList':
                renderErrorList(message.errors);
                break;
              case 'updateProgressStep':
                updateStep(message.stepNumber, message.status, message.text);
                break;
              case 'updateProgressText':
                updateProgressText(message.text);
                break;
              case 'hideProgress':
                hideProgress();
                break;
              case 'resetButtonState':
                resetButtonState();
                break;
              case 'updateCurrentFile':
                updateCurrentFile(message.filePath);
                break;
              case 'goToError':
                goToError(message.line, message.column, message.filePath);
                break;
            }
          });

          // 초기 로드
          window.addEventListener('load', () => {
            // 초기 상태 설정
          });
        </script>
      </body>
      </html>
    `;
  }

  public getStaticAnalysisPanel(): vscode.WebviewPanel | undefined {
    return this.staticAnalysisPanel;
  }

  public getDynamicAnalysisPanel(): vscode.WebviewPanel | undefined {
    return this.dynamicAnalysisPanel;
  }

  // 실시간 분석 결과가 업데이트될 때 웹뷰에 자동으로 반영
  public updateRealtimeErrorsInWebview(): void {
    if (this.staticAnalysisPanel) {
      const errors = getRealtimeAnalysisResults();
      this.staticAnalysisPanel.webview.postMessage({
        command: 'updateRealtimeErrors',
        errors: errors
      });
    }
  }

  private async handleStaticAnalysisMessage(message: any): Promise<void> {
    if (!this.staticAnalysisPanel) return;

    switch (message.command) {
      case 'toggleRealtimeAnalysis':
        await this.toggleRealtimeAnalysis();
        break;
      case 'runPreciseAnalysis':
        await this.runPreciseAnalysis();
        break;
      case 'getRealtimeErrors':
        await this.getRealtimeErrors();
        break;
      case 'getPreciseErrors':
        await this.getPreciseErrors();
        break;
      case 'goToError':
        await this.goToError(message.line, message.column, message.filePath);
        break;
    }
  }

  private async toggleRealtimeAnalysis(): Promise<void> {
    if (!this.staticAnalysisPanel) return;

    const config = vscode.workspace.getConfiguration("findRuntimeErr");
    const currentEnable = config.get<boolean>("enable", true);
    const newEnable = !currentEnable;
    
    await config.update("enable", newEnable, vscode.ConfigurationTarget.Workspace);
    
    this.staticAnalysisPanel.webview.postMessage({
      command: 'updateRealtimeStatus',
      status: newEnable ? '활성화됨' : '비활성화됨'
    });

    // 토글 후 즉시 목록 갱신
    await this.getRealtimeErrors();

    vscode.window.showInformationMessage(
      `실시간 분석이 ${newEnable ? '활성화' : '비활성화'}되었습니다.`
    );
  }

  private async runPreciseAnalysis(): Promise<void> {
    if (!this.staticAnalysisPanel) return;

    let editor = vscode.window.activeTextEditor;
    let targetFile: string | undefined;

    // 현재 활성화된 에디터가 Python 파일인 경우 해당 파일 사용
    if (editor && editor.document.languageId === "python") {
      targetFile = editor.document.fileName;
      this.lastSelectedPythonFile = targetFile; // 마지막 선택된 Python 파일 업데이트
    } else {
      // 마지막으로 선택된 Python 파일이 있는 경우 해당 파일 사용
      if (this.lastSelectedPythonFile) {
        try {
          const uri = vscode.Uri.file(this.lastSelectedPythonFile);
          const document = await vscode.workspace.openTextDocument(uri);
          editor = await vscode.window.showTextDocument(document, { 
            viewColumn: vscode.ViewColumn.One,
            preview: false
          });
          targetFile = this.lastSelectedPythonFile;
          
          vscode.window.showInformationMessage(`이전에 선택된 Python 파일을 사용합니다: ${this.lastSelectedPythonFile}`);
        } catch (error) {
          console.error('이전 Python 파일을 열 수 없습니다:', error);
          this.lastSelectedPythonFile = undefined; // 파일을 열 수 없으면 초기화
        }
      }
    }

    // 여전히 Python 파일이 없는 경우 워크스페이스에서 Python 파일 찾기
    if (!editor || editor.document.languageId !== "python") {
      // 워크스페이스에서 Python 파일 찾기
      const pythonFiles = await vscode.workspace.findFiles('**/*.py', '**/node_modules/**');
      
      if (pythonFiles.length > 0) {
        // 첫 번째 Python 파일을 사용
        const firstPythonFile = pythonFiles[0];
        try {
          const document = await vscode.workspace.openTextDocument(firstPythonFile);
          editor = await vscode.window.showTextDocument(document, { 
            viewColumn: vscode.ViewColumn.One,
            preview: false
          });
          targetFile = firstPythonFile.fsPath;
          this.lastSelectedPythonFile = targetFile; // 마지막 선택된 Python 파일 업데이트
          
          // 파일 정보 업데이트
          this.updateStaticAnalysisFileInfo();
          
          vscode.window.showInformationMessage(`Python 파일을 찾아서 분석을 시작합니다: ${firstPythonFile.fsPath}`);
        } catch (error) {
          console.error('Python 파일을 열 수 없습니다:', error);
        }
      }
    }

    // 여전히 Python 파일이 없는 경우
    if (!editor || editor.document.languageId !== "python") {
      vscode.window.showWarningMessage("Python 파일을 열어주세요.");
      return;
    }

    // 현재 파일 정보를 웹뷰에 업데이트
    this.staticAnalysisPanel.webview.postMessage({
      command: 'updateCurrentFile',
      filePath: targetFile
    });

    this.staticAnalysisPanel.webview.postMessage({
      command: 'updatePreciseStatus',
      status: '분석 중...'
    });

    try {
      // 정밀 분석 실행 (기존 로직 활용)
      await vscode.commands.executeCommand("findRuntimeErr.analyzeCurrentFile");
      
      this.staticAnalysisPanel.webview.postMessage({
        command: 'updatePreciseStatus',
        status: '완료됨'
      });

      // 분석 결과 가져오기
      await this.getPreciseErrors();
    } catch (error) {
      this.staticAnalysisPanel.webview.postMessage({
        command: 'updatePreciseStatus',
        status: '오류 발생'
      });
      vscode.window.showErrorMessage(`정밀 분석 중 오류가 발생했습니다: ${error}`);
    }
  }

  private async getRealtimeErrors(): Promise<void> {
    if (!this.staticAnalysisPanel) return;

    // 실시간 분석 결과를 가져오기
    const errors = getRealtimeAnalysisResults();
    
    this.staticAnalysisPanel.webview.postMessage({
      command: 'updateRealtimeErrors',
      errors: errors
    });
  }

  private async getPreciseErrors(): Promise<void> {
    if (!this.staticAnalysisPanel) return;

    // 정밀 분석 결과를 가져오기
    const errors = getPreciseAnalysisResults();
    
    this.staticAnalysisPanel.webview.postMessage({
      command: 'updatePreciseErrors',
      errors: errors
    });
  }

  private async goToError(line: number, column: number, filePath?: string): Promise<void> {
    let targetEditor: vscode.TextEditor | undefined;
    
    // 파일 경로가 제공된 경우 해당 파일을 열거나 찾기
    if (filePath) {
      try {
        const uri = vscode.Uri.file(filePath);
        const document = await vscode.workspace.openTextDocument(uri);
        targetEditor = await vscode.window.showTextDocument(document, { 
          viewColumn: vscode.ViewColumn.One,
          preview: false
        });
      } catch (error) {
        vscode.window.showErrorMessage(`파일을 열 수 없습니다: ${filePath}`);
        return;
      }
    } else {
      // 파일 경로가 없는 경우 현재 활성화된 에디터 사용
      targetEditor = vscode.window.activeTextEditor;
      if (!targetEditor || targetEditor.document.languageId !== "python") {
        vscode.window.showWarningMessage("Python 파일을 열어주세요.");
        return;
      }
    }

    try {
      // 해당 위치로 이동
      const position = new vscode.Position(
        Math.max(0, line - 1), // 0-based index로 변환, 최소 0
        Math.max(0, column - 1) // 0-based index로 변환, 최소 0
      );
      
      targetEditor.selection = new vscode.Selection(position, position);
      targetEditor.revealRange(new vscode.Range(position, position), vscode.TextEditorRevealType.InCenter);
      
    } catch (error) {
      vscode.window.showErrorMessage(`위치로 이동하는 중 오류가 발생했습니다: ${error}`);
    }
  }

  private async handleDynamicAnalysisMessage(message: any): Promise<void> {
    if (!this.dynamicAnalysisPanel) return;

    switch (message.command) {
      case 'generateAITests':
        await this.generateAITests();
        break;
      case 'runUserTests':
        await this.runUserTests(message.testInput);
        break;
      case 'updateAITestStatus':
        await this.updateAITestStatus(message.status);
        break;
      case 'updateUserTestStatus':
        await this.updateUserTestStatus(message.status);
        break;
      case 'updateTestResults':
        await this.updateTestResults(message.results);
        break;
      case 'goToError':
        await this.goToError(message.line, message.column, message.filePath);
        break;
    }
  }

  private async generateAITests(): Promise<void> {
    if (!this.dynamicAnalysisPanel) return;

    let editor = vscode.window.activeTextEditor;
    let targetFile: string | undefined;

    // 현재 활성화된 에디터가 Python 파일인 경우 해당 파일 사용
    if (editor && editor.document.languageId === "python") {
      targetFile = editor.document.fileName;
      this.lastSelectedPythonFile = targetFile; // 마지막 선택된 Python 파일 업데이트
    } else {
      // 마지막으로 선택된 Python 파일이 있는 경우 해당 파일 사용
      if (this.lastSelectedPythonFile) {
        try {
          const uri = vscode.Uri.file(this.lastSelectedPythonFile);
          const document = await vscode.workspace.openTextDocument(uri);
          editor = await vscode.window.showTextDocument(document, { 
            viewColumn: vscode.ViewColumn.One,
            preview: false
          });
          targetFile = this.lastSelectedPythonFile;
          
          vscode.window.showInformationMessage(`이전에 선택된 Python 파일을 사용합니다: ${this.lastSelectedPythonFile}`);
        } catch (error) {
          console.error('이전 Python 파일을 열 수 없습니다:', error);
          this.lastSelectedPythonFile = undefined; // 파일을 열 수 없으면 초기화
        }
      }
    }

    // 여전히 Python 파일이 없는 경우 워크스페이스에서 Python 파일 찾기
    if (!editor || editor.document.languageId !== "python") {
      // 워크스페이스에서 Python 파일 찾기
      const pythonFiles = await vscode.workspace.findFiles('**/*.py', '**/node_modules/**');
      
      if (pythonFiles.length > 0) {
        // 첫 번째 Python 파일을 사용
        const firstPythonFile = pythonFiles[0];
        try {
          const document = await vscode.workspace.openTextDocument(firstPythonFile);
          editor = await vscode.window.showTextDocument(document, { 
            viewColumn: vscode.ViewColumn.One,
            preview: false
          });
          targetFile = firstPythonFile.fsPath;
          this.lastSelectedPythonFile = targetFile; // 마지막 선택된 Python 파일 업데이트
          
          // 파일 정보 업데이트
          this.updateCurrentFileInfo();
          
          vscode.window.showInformationMessage(`Python 파일을 찾아서 분석을 시작합니다: ${firstPythonFile.fsPath}`);
        } catch (error) {
          console.error('Python 파일을 열 수 없습니다:', error);
        }
      }
    }

    // 여전히 Python 파일이 없는 경우
    if (!editor || editor.document.languageId !== "python") {
      // 버튼 상태 복구
      this.dynamicAnalysisPanel.webview.postMessage({
        command: 'resetButtonState'
      });
      
      // 진행 상황을 오류 상태로 표시
      this.dynamicAnalysisPanel.webview.postMessage({
        command: 'updateProgressStep',
        stepNumber: 1,
        status: 'error',
        text: 'Python 파일이 필요합니다'
      });
      this.dynamicAnalysisPanel.webview.postMessage({
        command: 'updateProgressText',
        text: 'Python 파일을 열어주세요.'
      });
      
      vscode.window.showWarningMessage("Python 파일을 열어주세요.");
      return;
    }

    try {
      // 1단계: AI 테스트케이스 생성
      this.dynamicAnalysisPanel.webview.postMessage({
        command: 'updateProgressStep',
        stepNumber: 1,
        status: 'active',
        text: 'AI 테스트케이스 생성 중...'
      });
      this.dynamicAnalysisPanel.webview.postMessage({
        command: 'updateProgressText',
        text: 'AI를 사용하여 테스트케이스를 생성하고 있습니다...'
      });

      // 동적분석 실행 전에 Python 파일이 활성화되어 있는지 확인
      let currentEditor = vscode.window.activeTextEditor;
      if (!currentEditor || currentEditor.document.languageId !== "python" || currentEditor.document.fileName !== targetFile) {
        // Python 파일이 활성화되지 않았거나 다른 파일이 활성화된 경우, 대상 파일을 다시 활성화
        if (targetFile) {
          try {
            const uri = vscode.Uri.file(targetFile);
            const document = await vscode.workspace.openTextDocument(uri);
            currentEditor = await vscode.window.showTextDocument(document, { 
              viewColumn: vscode.ViewColumn.One,
              preview: false
            });
          } catch (error) {
            console.error('Python 파일을 활성화할 수 없습니다:', error);
            throw new Error('Python 파일을 활성화할 수 없습니다.');
          }
        } else {
          throw new Error('분석할 Python 파일이 지정되지 않았습니다.');
        }
      }

      // 동적분석 명령어 실행 및 완료 대기
      await vscode.commands.executeCommand("findRuntimeErr.runDynamicAnalysis");

      // AI 테스트케이스 생성 완료
      this.dynamicAnalysisPanel.webview.postMessage({
        command: 'updateProgressStep',
        stepNumber: 1,
        status: 'completed',
        text: 'AI 테스트케이스 생성 완료'
      });

      // 생성된 테스트케이스 정보 출력
      this.dynamicAnalysisPanel.webview.postMessage({
        command: 'updateProgressText',
        text: 'AI 테스트케이스 생성이 완료되었습니다. 함수 테스트를 시작합니다.'
      });

      // 2단계: 함수 테스트 실행
      this.dynamicAnalysisPanel.webview.postMessage({
        command: 'updateProgressStep',
        stepNumber: 2,
        status: 'active',
        text: '함수 테스트 실행 중...'
      });
      this.dynamicAnalysisPanel.webview.postMessage({
        command: 'updateProgressText',
        text: '생성된 테스트케이스로 함수를 테스트하고 있습니다...'
      });

      // 함수 테스트 실행 완료
      this.dynamicAnalysisPanel.webview.postMessage({
        command: 'updateProgressStep',
        stepNumber: 2,
        status: 'completed',
        text: '함수 테스트 실행 완료'
      });

      // 테스트 결과와 오류 목록을 웹뷰에 전송
      const dynamicResults = getDynamicAnalysisResults();
      
      if (dynamicResults.length > 0) {
        // 실제 동적분석 결과를 사용
        const latestResult = dynamicResults[dynamicResults.length - 1];
        
        // AI 테스트케이스 결과 생성
        const testResults = [
          {
            functionName: "AI 생성 테스트케이스",
            testCases: latestResult.errors.map((error: any) => {
              // 오류 메시지에서 함수명 추출 시도
              const functionMatch = error.message.match(/Function `(.+?)`/);
              const functionName = functionMatch ? functionMatch[1] : '알 수 없는 함수';
              
              return {
                input: `함수: ${functionName}`,
                expected: "정상 실행 (예상)",
                actual: `${error.errorType}: ${error.message}`,
                success: false
              };
            })
          }
        ];

        // 오류 목록 생성 (line, column 정보 포함)
        const errors = latestResult.errors.map((error: any) => ({
          errorType: error.errorType,
          message: error.message,
          line: error.line || 1,
          column: error.column || 0,
          filePath: targetFile,
          memoryUsage: error.memoryUsage || null
        }));

        this.dynamicAnalysisPanel.webview.postMessage({
          command: 'updateTestResults',
          results: testResults
        });

        this.dynamicAnalysisPanel.webview.postMessage({
          command: 'updateErrorList',
          errors: errors
        });
      } else {
        // 결과가 없는 경우 빈 결과 표시
        this.dynamicAnalysisPanel.webview.postMessage({
          command: 'updateTestResults',
          results: []
        });

        this.dynamicAnalysisPanel.webview.postMessage({
          command: 'updateErrorList',
          errors: []
        });
      }

      this.dynamicAnalysisPanel.webview.postMessage({
        command: 'updateProgressText',
        text: '분석이 완료되었습니다!'
      });

      // 버튼 상태 복구
      this.dynamicAnalysisPanel.webview.postMessage({
        command: 'resetButtonState'
      });

    } catch (error) {
      // 오류 발생 시 진행 상황 업데이트
      this.dynamicAnalysisPanel.webview.postMessage({
        command: 'updateProgressStep',
        stepNumber: 2,
        status: 'error',
        text: '오류 발생'
      });
      this.dynamicAnalysisPanel.webview.postMessage({
        command: 'updateProgressText',
        text: '분석 중 오류가 발생했습니다.'
      });

      // 버튼 상태 복구
      this.dynamicAnalysisPanel.webview.postMessage({
        command: 'resetButtonState'
      });

      vscode.window.showErrorMessage(`AI 테스트 생성 중 오류가 발생했습니다: ${error}`);
    }
  }

  private async runUserTests(testInput: string): Promise<void> {
    if (!this.dynamicAnalysisPanel) return;

    this.dynamicAnalysisPanel.webview.postMessage({
      command: 'updateUserTestStatus',
      status: '분석 중...'
    });

    try {
      // 사용자 테스트 실행 로직 구현
      // 이 부분은 실제 구현 로직에 따라 변경될 수 있습니다.
      this.dynamicAnalysisPanel.webview.postMessage({
        command: 'updateUserTestStatus',
        status: '완료됨'
      });
    } catch (error) {
      this.dynamicAnalysisPanel.webview.postMessage({
        command: 'updateUserTestStatus',
        status: '오류 발생'
      });
      vscode.window.showErrorMessage(`사용자 테스트 실행 중 오류가 발생했습니다: ${error}`);
    }
  }

  private async updateAITestStatus(status: string): Promise<void> {
    if (!this.dynamicAnalysisPanel) return;

    this.dynamicAnalysisPanel.webview.postMessage({
      command: 'updateAITestStatus',
      status: status
    });
  }

  private async updateUserTestStatus(status: string): Promise<void> {
    if (!this.dynamicAnalysisPanel) return;

    this.dynamicAnalysisPanel.webview.postMessage({
      command: 'updateUserTestStatus',
      status: status
    });
  }

  private async updateTestResults(results: string): Promise<void> {
    if (!this.dynamicAnalysisPanel) return;

    this.dynamicAnalysisPanel.webview.postMessage({
      command: 'updateTestResults',
      results: results
    });
  }

  // Python 실행 파일 경로 가져오기
  private async getPythonExecutable(): Promise<string> {
    try {
      // 현재 활성화된 Python 인터프리터 사용
      const pythonPath = await vscode.commands.executeCommand('python.interpreterPath') as string;
      if (pythonPath) {
        return pythonPath;
      }
    } catch (error) {
      console.warn('Python 인터프리터 경로를 가져올 수 없습니다:', error);
    }

    // 기본 Python 명령어 사용
    return 'python';
  }

  // Python 패키지 확인
  private checkPythonPackages(pythonExecutable: string): {
    missing: string[];
  } {
    const requiredPackages = ["parso", "astroid", "networkx", "astor", "google-genai"];
    const missingPackages = requiredPackages.filter((pkg) => {
      try {
        // google-genai는 import 테스트도 추가로 수행
        if (pkg === "google-genai") {
          // 먼저 pip show로 확인
          execSync(`"${pythonExecutable}" -m pip show "${pkg}"`, {
            stdio: "pipe",
          });
          
          // 추가로 import 테스트 수행
          try {
            execSync(`"${pythonExecutable}" -c "from google import genai; print('google-genai import successful')"`, {
              stdio: "pipe",
            });
          } catch (importError) {
            console.warn("google-genai import test failed:", importError);
            return true; // import 실패 시 누락된 것으로 간주
          }
          return false;
        } else {
          // 일반 패키지는 pip show와 import 테스트 모두 수행
          execSync(`"${pythonExecutable}" -m pip show "${pkg}"`, {
            stdio: "pipe",
          });
          
          // import 테스트도 수행
          try {
            execSync(`"${pythonExecutable}" -c "import ${pkg}; print('${pkg} import successful')"`, {
              stdio: "pipe",
            });
          } catch (importError) {
            console.warn(`${pkg} import test failed:`, importError);
            return true; // import 실패 시 누락된 것으로 간주
          }
          return false;
        }
      } catch {
        return true;
      }
    });
    return { missing: missingPackages };
  }

  // 누락된 패키지 설치 (설치 실패 시에도 계속 진행)
  private async installMissingPackages(missingPackages: string[], pythonExecutable: string): Promise<string[]> {
    const failedPackages: string[] = [];
    
    for (const pkg of missingPackages) {
      try {
        console.log(`Installing ${pkg}...`);
        
        let installCommand: string;
        
        // google-genai 패키지는 특별한 처리가 필요할 수 있음
        if (pkg === "google-genai") {
          installCommand = `"${pythonExecutable}" -m pip install "google-genai>=0.3.0"`;
        } else {
          installCommand = `"${pythonExecutable}" -m pip install "${pkg}"`;
        }
        
        execSync(installCommand, { stdio: "pipe" });
        console.log(`Successfully installed ${pkg}`);
        
        // 설치 후 다시 확인
        try {
          if (pkg === "google-genai") {
            execSync(`"${pythonExecutable}" -c "from google import genai; print('google-genai import successful')"`, {
              stdio: "pipe",
            });
          } else {
            execSync(`"${pythonExecutable}" -c "import ${pkg}; print('${pkg} import successful')"`, {
              stdio: "pipe",
            });
          }
        } catch (verifyError) {
          console.warn(`Package ${pkg} installed but import failed:`, verifyError);
          failedPackages.push(pkg);
        }
        
      } catch (error) {
        console.error(`Failed to install ${pkg}:`, error);
        
        // google-genai 설치 실패 시 대안 시도
        if (pkg === "google-genai") {
          try {
            console.log("Trying alternative installation for google-genai...");
            const altCommand = `"${pythonExecutable}" -m pip install --upgrade google-genai`;
            execSync(altCommand, { stdio: "pipe" });
            console.log("Successfully installed google-genai with alternative method");
            
            // 대안 설치 후 확인
            try {
              execSync(`"${pythonExecutable}" -c "from google import genai; print('google-genai import successful')"`, {
                stdio: "pipe",
              });
            } catch (verifyError) {
              console.warn("google-genai alternative installation succeeded but import failed:", verifyError);
              failedPackages.push(pkg);
            }
          } catch (altError) {
            console.error("Alternative installation also failed:", altError);
            failedPackages.push(pkg);
          }
        } else {
          failedPackages.push(pkg);
        }
      }
    }
    
    return failedPackages;
  }

  // 현재 파일 정보 업데이트
  private updateCurrentFileInfo(): void {
    if (!this.dynamicAnalysisPanel) return;

    const editor = vscode.window.activeTextEditor;
    let filePath: string | undefined;

    // 현재 활성화된 에디터가 Python 파일인 경우 해당 파일 사용
    if (editor && editor.document.languageId === "python") {
      filePath = editor.document.fileName;
      this.lastSelectedPythonFile = filePath; // 마지막 선택된 Python 파일 업데이트
    } else {
      // 현재 활성화된 에디터가 Python 파일이 아닌 경우 마지막으로 선택된 Python 파일 사용
      filePath = this.lastSelectedPythonFile;
    }

    this.dynamicAnalysisPanel.webview.postMessage({
      command: 'updateCurrentFile',
      filePath: filePath
    });
  }

  private updateStaticAnalysisFileInfo(): void {
    if (!this.staticAnalysisPanel) return;

    const editor = vscode.window.activeTextEditor;
    let filePath: string | undefined;

    // 현재 활성화된 에디터가 Python 파일인 경우 해당 파일 사용
    if (editor && editor.document.languageId === "python") {
      filePath = editor.document.fileName;
      this.lastSelectedPythonFile = filePath; // 마지막 선택된 Python 파일 업데이트
    } else {
      // 현재 활성화된 에디터가 Python 파일이 아닌 경우 마지막으로 선택된 Python 파일 사용
      filePath = this.lastSelectedPythonFile;
    }

    this.staticAnalysisPanel.webview.postMessage({
      command: 'updateCurrentFile',
      filePath: filePath
    });
  }
} 