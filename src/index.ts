import { IDisposable, DisposableDelegate } from '@lumino/disposable';

import { Widget } from '@lumino/widgets';

import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';

import { DocumentRegistry } from '@jupyterlab/docregistry';

import {
  NotebookPanel,
  INotebookModel,
  INotebookTracker,
  NotebookActions,
} from '@jupyterlab/notebook';

/**
 * Initialization data for the jupyter-tensorboard extension.
 */
const plugin: JupyterFrontEndPlugin<void> = {
  id: 'jupyter_tensorboard:plugin',
  description: 'A JupyterLab extension.',
  autoStart: true,
  requires: [INotebookTracker as any],
  activate: activate
};

/**
 * A notebook widget extension that adds a widget in the notebook header (widget below the toolbar).
//  */
export class WidgetExtension
  implements DocumentRegistry.IWidgetExtension<NotebookPanel, INotebookModel> {
  /**
   * Create a new extension object.
   */
  createNew(
    panel: NotebookPanel,
    context: DocumentRegistry.IContext<INotebookModel>
  ): IDisposable {
    const widget = new Widget({ node: Private.createNode() });
    widget.addClass('jp-myextension-myheader');

    panel.contentHeader.insertWidget(0, widget as any);
    return new DisposableDelegate(() => {
      widget.dispose();
    });
  }
}

/**
 * Activate the extension.
 */
function activate(app: JupyterFrontEnd, notebookTracker: INotebookTracker) {
  // Nothing is needed
  console.log('JupyterLab extension jupyter-tensorboard is activated!');

  startWS(notebookTracker);

  app.docRegistry.addWidgetExtension('Notebook', new WidgetExtension() as any);
}

function startWS(notebookTracker: INotebookTracker) {
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
export default plugin;

// /**
//  * Private helpers
//  */
namespace Private {
  /**
   * Generate the widget node
   */
  export function createNode(): HTMLElement {
    const span = document.createElement('span');
    span.textContent = 'If you are seeing this, the extension is working!!';
    return span;
  }

  export function runAll(notebookTracker: INotebookTracker) {
    if (notebookTracker.currentWidget) {
      const sessionContext = notebookTracker.currentWidget.sessionContext;
      if (sessionContext) {
        NotebookActions.runAll(
          notebookTracker.currentWidget.content,
          sessionContext
        );
        console.log('Running cells');
      }
    }
  }

  export function runCell(
    notebookTracker: INotebookTracker,
    index: number,
    ws: WebSocket
  ) {
    if (
      notebookTracker.currentWidget &&
      notebookTracker.currentWidget.content
    ) {
      const realCell = notebookTracker.currentWidget.content.widgets.at(index);
      realCell?.activate();
      realCell?.ready.then(_ => {
        if (
          notebookTracker.currentWidget &&
          notebookTracker.currentWidget.content
        ) {
          const sessionContext = notebookTracker.currentWidget.sessionContext;
          notebookTracker.currentWidget?.content.deselectAll();

          notebookTracker.currentWidget?.content.select(realCell);

          NotebookActions.runCells(
            notebookTracker.currentWidget.content,
            notebookTracker.currentWidget?.content.selectedCells,
            sessionContext
          ).then((val: boolean) => {
            ws.send(
              JSON.stringify({
                type: 'setOutput',
                data: realCell.model.sharedModel.toJSON()
              })
            );
          });
        }
      });
    }
  }

  export function setNotebook(
    notebookTracker: INotebookTracker,
    json: any,
    test: string = 'test'
  ) {
    // json = JSON.parse(json);
    json.metadata.orig_nbformat = 4;
    console.log(json);
    console.log(test);
    // json = JSON.stringify(json);
    notebookTracker.currentWidget?.content.model?.fromJSON(json);
  }
}