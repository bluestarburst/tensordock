import { IDisposable, DisposableDelegate } from '@lumino/disposable';

import { Widget } from '@lumino/widgets';

import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';

import { DocumentRegistry } from '@jupyterlab/docregistry';

import {
  Notebook,
  NotebookPanel,
  INotebookModel,
  INotebookTracker,
  NotebookActions
} from '@jupyterlab/notebook';

/**
 * Initialization data for the Jupyter-Tensorboard extension.
 */
const plugin: JupyterFrontEndPlugin<void> = {
  id: 'Jupyter-Tensorboard:plugin',
  description: 'A JupyterLab extension.',
  autoStart: true,
  requires: [INotebookTracker],
  activate: activate
};

/**
 * A notebook widget extension that adds a widget in the notebook header (widget below the toolbar).
//  */
export class WidgetExtension
  implements DocumentRegistry.IWidgetExtension<NotebookPanel, INotebookModel>
{
  /**
   * Create a new extension object.
   */
  createNew(
    panel: NotebookPanel,
    context: DocumentRegistry.IContext<INotebookModel>
  ): IDisposable {
    const widget = new Widget({ node: Private.createNode() });
    widget.addClass('jp-myextension-myheader');

    panel.contentHeader.insertWidget(0, widget);
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

  const ws = new WebSocket('ws://localhost:3000');
  ws.onopen = () => {
    ws.send('Hello, Server');
  };
  ws.onmessage = event => {
    console.log('Message from server ', event.data);
    const data = JSON.parse(event.data);
    switch (data.type) {
      case 'runCell':
        // run cell at index
        console.log('Running cells');
        Private.runAll(notebookTracker);
        break;
      default:
        console.log('Unknown message');
    }
  };

  app.docRegistry.addWidgetExtension('Notebook', new WidgetExtension());
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
    span.textContent = 'If you are seeing this, the extension is working!';
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
}
