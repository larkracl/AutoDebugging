// src/webview/static.js

const vscode = acquireVsCodeApi();

/**
 * 탭을 전환하는 함수
 * @param {'realtime' | 'precise'} tabName - 활성화할 탭의 이름
 */
function switchTab(tabName) {
    // 모든 탭 버튼에서 'active' 클래스 제거
    document.querySelectorAll('.tab-button').forEach(btn => btn.classList.remove('active'));
    // 클릭된 버튼에 'active' 클래스 추가
    document.querySelector(`[data-tab="${tabName}"]`).classList.add('active');

    // 모든 탭 콘텐츠 숨기기
    document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
    // 선택된 탭 콘텐츠 보이기
    document.getElementById(`${tabName}-tab`).classList.add('active');
    
    // 탭 전환 시 해당 탭의 최신 데이터 요청
    if (tabName === 'realtime') {
        vscode.postMessage({ command: 'getRealtimeErrors' });
    } else if (tabName === 'precise') {
        vscode.postMessage({ command: 'getPreciseErrors' });
    }
}

/**
 * 오류 목록을 HTML로 렌더링하는 함수
 * @param {string} containerId - 오류 목록을 표시할 div의 ID
 * @param {Array<object>} errors - 표시할 오류 객체의 배열
 */
function renderErrorList(containerId, errors) {
    const container = document.getElementById(containerId);
    if (!container) return;

    if (!errors || errors.length === 0) {
        container.innerHTML = '<div class="no-errors">발견된 오류가 없습니다.</div>';
        return;
    }

    const errorHtml = errors.map(error => `
        <div class="error-item" 
             data-line="${error.line}" 
             data-column="${error.column}" 
             data-filepath="${error.filePath || ''}"
             title="Click to go to error location">
            <div class="error-header">
                <span class="error-type">${error.errorType || 'Error'}</span>
                <span class="error-location">Line ${error.line || 'N/A'}, Col ${error.column || 'N/A'}</span>
            </div>
            <div class="error-message">${error.message}</div>
        </div>
    `).join('');
    
    container.innerHTML = errorHtml;

    // 생성된 각 오류 아이템에 클릭 이벤트 리스너 추가
    container.querySelectorAll('.error-item').forEach(item => {
        item.addEventListener('click', () => {
            vscode.postMessage({
                command: 'goToError',
                line: parseInt(item.dataset.line),
                column: parseInt(item.dataset.column),
                filePath: item.dataset.filepath
            });
        });
    });
}

/**
 * 현재 분석 중인 파일 정보를 업데이트하는 함수
 * @param {string | undefined} filePath - 현재 파일의 전체 경로
 */
function updateCurrentFile(filePath) {
    const filePathElement = document.getElementById('currentFilePath');
    if (!filePathElement) return;

    if (filePath) {
        const fileName = filePath.split(/[\\/]/).pop();
        filePathElement.textContent = `${fileName} (${filePath})`;
        filePathElement.classList.remove('no-file');
    } else {
        filePathElement.textContent = '분석할 Python 파일을 열어주세요.';
        filePathElement.classList.add('no-file');
    }
}

/**
 * 실시간 분석 토글 버튼과 상태 텍스트를 업데이트하는 함수
 * @param {boolean} isEnable - 실시간 분석 활성화 여부
 */
function updateRealtimeStatusUI(isEnable) {
    const statusDiv = document.getElementById('realtimeStatus');
    const toggleBtn = document.getElementById('toggleRealtimeBtn');
    if (statusDiv && toggleBtn) {
        statusDiv.textContent = `상태: ${isEnable ? '활성화됨' : '비활성화됨'}`;
        toggleBtn.textContent = isEnable ? '실시간 분석 비활성화' : '실시간 분석 활성화';
    }
}

// DOM이 완전히 로드된 후 스크립트 실행
document.addEventListener('DOMContentLoaded', () => {
    // 탭 버튼에 이벤트 리스너 할당
    document.querySelectorAll('.tab-button').forEach(button => {
        button.addEventListener('click', (event) => {
            const tabName = (event.currentTarget as HTMLElement).dataset.tab;
            if (tabName) {
                switchTab(tabName);
            }
        });
    });

    // 각 버튼에 이벤트 리스너 할당
    document.getElementById('refreshRealtimeBtn')?.addEventListener('click', () => vscode.postMessage({ command: 'getRealtimeErrors' }));
    document.getElementById('refreshPreciseBtn')?.addEventListener('click', () => vscode.postMessage({ command: 'getPreciseErrors' }));
    document.getElementById('runPreciseBtn')?.addEventListener('click', () => vscode.postMessage({ command: 'runPreciseAnalysis' }));
    document.getElementById('toggleRealtimeBtn')?.addEventListener('click', () => vscode.postMessage({ command: 'toggleRealtimeAnalysis' }));

    // VSCode 확장 프로그램으로부터 메시지 수신
    window.addEventListener('message', event => {
        const message = event.data;
        switch (message.command) {
            case 'updateRealtimeErrors':
                renderErrorList('realtimeErrorList', message.errors);
                break;
            case 'updatePreciseErrors':
                renderErrorList('preciseErrorList', message.errors);
                break;
            case 'updatePreciseStatus':
                const preciseStatus = document.getElementById('preciseStatus');
                if (preciseStatus) preciseStatus.textContent = `상태: ${message.status}`;
                break;
            case 'updateCurrentFile':
                updateCurrentFile(message.filePath);
                break;
            case 'updateRealtimeStatus':
                updateRealtimeStatusUI(message.isEnable);
                break;
        }
    });
    
    // 웹뷰가 로드될 때, 필요한 초기 데이터를 확장 프로그램에 요청
    vscode.postMessage({ command: 'getCurrentFile' });
    vscode.postMessage({ command: 'getRealtimeStatus' });
    vscode.postMessage({ command: 'getRealtimeErrors' });
    vscode.postMessage({ command: 'getPreciseErrors' });
});