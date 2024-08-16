"use strict";
(self["webpackChunktensorboard"] = self["webpackChunktensorboard"] || []).push([["lib_index_js"],{

/***/ "./lib/index.js":
/*!**********************!*\
  !*** ./lib/index.js ***!
  \**********************/
/***/ ((__unused_webpack_module, __webpack_exports__, __webpack_require__) => {

__webpack_require__.r(__webpack_exports__);
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   WidgetExtension: () => (/* binding */ WidgetExtension),
/* harmony export */   "default": () => (__WEBPACK_DEFAULT_EXPORT__)
/* harmony export */ });
/* harmony import */ var _lumino_disposable__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(/*! @lumino/disposable */ "webpack/sharing/consume/default/@lumino/disposable");
/* harmony import */ var _lumino_disposable__WEBPACK_IMPORTED_MODULE_0___default = /*#__PURE__*/__webpack_require__.n(_lumino_disposable__WEBPACK_IMPORTED_MODULE_0__);
/* harmony import */ var _lumino_widgets__WEBPACK_IMPORTED_MODULE_1__ = __webpack_require__(/*! @lumino/widgets */ "webpack/sharing/consume/default/@lumino/widgets");
/* harmony import */ var _lumino_widgets__WEBPACK_IMPORTED_MODULE_1___default = /*#__PURE__*/__webpack_require__.n(_lumino_widgets__WEBPACK_IMPORTED_MODULE_1__);
/* harmony import */ var _jupyterlab_notebook__WEBPACK_IMPORTED_MODULE_2__ = __webpack_require__(/*! @jupyterlab/notebook */ "webpack/sharing/consume/default/@jupyterlab/notebook");
/* harmony import */ var _jupyterlab_notebook__WEBPACK_IMPORTED_MODULE_2___default = /*#__PURE__*/__webpack_require__.n(_jupyterlab_notebook__WEBPACK_IMPORTED_MODULE_2__);



/**
 * Initialization data for the jupyter-tensorboard extension.
 */
const plugin = {
    id: 'jupyter_tensorboard:plugin',
    description: 'A JupyterLab extension.',
    autoStart: true,
    requires: [_jupyterlab_notebook__WEBPACK_IMPORTED_MODULE_2__.INotebookTracker],
    activate: activate
};
/**
 * A notebook widget extension that adds a widget in the notebook header (widget below the toolbar).
//  */
class WidgetExtension {
    /**
     * Create a new extension object.
     */
    createNew(panel, context) {
        const widget = new _lumino_widgets__WEBPACK_IMPORTED_MODULE_1__.Widget({ node: Private.createNode() });
        widget.addClass('jp-myextension-myheader');
        panel.contentHeader.insertWidget(0, widget);
        return new _lumino_disposable__WEBPACK_IMPORTED_MODULE_0__.DisposableDelegate(() => {
            widget.dispose();
        });
    }
}
/**
 * Activate the extension.
 */
function activate(app, notebookTracker) {
    // Nothing is needed
    console.log('JupyterLab extension jupyter-tensorboard is activated!');
    startWS(notebookTracker);
    // const ws = new WebSocket('ws://localhost:3000');
    // ws.onopen = () => {
    //   ws.send(JSON.stringify({ type: 'jupyter', data: '' }));
    //   clearInterval(interval);
    // };
    // ws.onmessage = event => {
    //   console.log('Message from server ', event.data);
    //   const data = JSON.parse(event.data);
    //   switch (data.type) {
    //     case 'runCell':
    //       // run cell at index
    //       console.log('Running cell ' + data.data);
    //       // Private.runAll(notebookTracker);
    //       Private.runCell(notebookTracker, data.data, ws);
    //       break;
    //     case 'setNotebook':
    //       Private.setNotebook(notebookTracker, JSON.parse(data.data));
    //       break;
    //     default:
    //       console.log('Unknown message');
    //   }
    // };
    // }, 1000);
    app.docRegistry.addWidgetExtension('Notebook', new WidgetExtension());
}
function startWS(notebookTracker) {
    const ws = new WebSocket('ws://localhost:3000');
    ws.onopen = () => {
        ws.send(JSON.stringify({ type: 'jupyter', data: '' }));
    };
    ws.onmessage = event => {
        console.log('Message from server ', event.data);
        const data = JSON.parse(event.data);
        switch (data.type) {
            case 'runCell':
                // run cell at index
                console.log('Running cell ' + data.data);
                // Private.runAll(notebookTracker);
                Private.runCell(notebookTracker, data.data, ws);
                break;
            case 'setNotebook':
                Private.setNotebook(notebookTracker, JSON.parse(data.data));
                break;
            default:
                console.log('Unknown message');
        }
    };
    ws.onclose = () => {
        console.log('WebSocket closed');
        ws.close();
        setTimeout(() => startWS(notebookTracker), 1000);
    };
    ws.onerror = () => {
        console.log('WebSocket error');
    };
}
// /**
//  * Export the plugin as default.
//  */
/* harmony default export */ const __WEBPACK_DEFAULT_EXPORT__ = (plugin);
// /**
//  * Private helpers
//  */
var Private;
(function (Private) {
    /**
     * Generate the widget node
     */
    function createNode() {
        const span = document.createElement('span');
        span.textContent = 'If you are seeing this, the extension is working!!';
        return span;
    }
    Private.createNode = createNode;
    function runAll(notebookTracker) {
        if (notebookTracker.currentWidget) {
            const sessionContext = notebookTracker.currentWidget.sessionContext;
            if (sessionContext) {
                _jupyterlab_notebook__WEBPACK_IMPORTED_MODULE_2__.NotebookActions.runAll(notebookTracker.currentWidget.content, sessionContext);
                console.log('Running cells');
            }
        }
    }
    Private.runAll = runAll;
    function runCell(notebookTracker, index, ws) {
        if (notebookTracker.currentWidget &&
            notebookTracker.currentWidget.content) {
            const realCell = notebookTracker.currentWidget.content.widgets.at(index);
            realCell === null || realCell === void 0 ? void 0 : realCell.activate();
            realCell === null || realCell === void 0 ? void 0 : realCell.ready.then(_ => {
                var _a, _b, _c;
                if (notebookTracker.currentWidget &&
                    notebookTracker.currentWidget.content) {
                    const sessionContext = notebookTracker.currentWidget.sessionContext;
                    (_a = notebookTracker.currentWidget) === null || _a === void 0 ? void 0 : _a.content.deselectAll();
                    (_b = notebookTracker.currentWidget) === null || _b === void 0 ? void 0 : _b.content.select(realCell);
                    _jupyterlab_notebook__WEBPACK_IMPORTED_MODULE_2__.NotebookActions.runCells(notebookTracker.currentWidget.content, (_c = notebookTracker.currentWidget) === null || _c === void 0 ? void 0 : _c.content.selectedCells, sessionContext).then((val) => {
                        ws.send(JSON.stringify({
                            type: 'setOutput',
                            data: realCell.model.sharedModel.toJSON()
                        }));
                    });
                }
            });
        }
    }
    Private.runCell = runCell;
    function setNotebook(notebookTracker, json, test = 'test') {
        var _a, _b;
        // json = JSON.parse(json);
        json.metadata.orig_nbformat = 4;
        console.log(json);
        console.log(test);
        // json = JSON.stringify(json);
        (_b = (_a = notebookTracker.currentWidget) === null || _a === void 0 ? void 0 : _a.content.model) === null || _b === void 0 ? void 0 : _b.fromJSON(json);
    }
    Private.setNotebook = setNotebook;
})(Private || (Private = {}));


/***/ })

}]);
//# sourceMappingURL=lib_index_js.436c4d957a2e316f1b06.js.map