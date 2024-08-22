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
  NotebookActions
} from '@jupyterlab/notebook';

import { ContentsManager } from '@jupyterlab/services';

// import WebSocket, { WebSocketServer } from 'ws';

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

    console.log('Creating new widget extension');

    panel.contentHeader.insertWidget(0, widget as any);
    return new DisposableDelegate(() => {
      widget.dispose();
    });
  }
}

async function setup_notebook(app: JupyterFrontEnd) {
  const manager = new ContentsManager();
  // Save the notebook
  const notebookName = 'tensorboard.ipynb';

  try {
    await app.commands.execute('docmanager:open', {
      path: notebookName,
      factory: 'Notebook'
    });
  } catch (e) {
    await manager.save(notebookName, {
      type: 'notebook',
      content: {
        cells: [],
        metadata: {
          kernelspec: {
            display_name: 'Python 3'
          },
          language_info: {
            name: 'python',
            version: '3.8.5'
          }
        },
        nbformat: 4,
        nbformat_minor: 2
      }
    });

    await app.commands.execute('docmanager:open', {
      path: notebookName,
      factory: 'Notebook'
    });
  }
}

/**
 * Activate the extension.
 */
function activate(app: JupyterFrontEnd, notebookTracker: INotebookTracker) {
  // Save the notebook
  setup_notebook(app);

  // Nothing is needed
  console.log('JupyterLab extension jupyter-tensorboard is activated!');

  startWS(app, notebookTracker);

  app.docRegistry.addWidgetExtension('Notebook', new WidgetExtension() as any);
}

function startWS(app: JupyterFrontEnd, notebookTracker: INotebookTracker) {
  // create client websocket
  const ws = new WebSocket('ws://localhost:5000');
  ws.onopen = () => {
    console.log('WebSocket opened');
    ws.send(JSON.stringify({ type: 'jupyter', data: '' }));
  };

  ws.onmessage = message => {
    console.log('Message from server ', message);
    const data = JSON.parse(message.data.toString());
    switch (data.type) {
      case 'runCell':
        // run cell at index
        console.log('Running cell ' + data.data);
        // Private.runAll(notebookTracker);
        Private.runCell(notebookTracker, data.data, ws);
        break;
      case 'setNotebook':
        Private.setNotebook(notebookTracker, app, data.data, 'test');
        break;
      case 'restartNotebook':
        console.log('Restarting notebook');
        Private.restartNotebook(notebookTracker);
        break;
      default:
        console.log('Unknown message');
    }
  };

  ws.onclose = () => {
    console.log('WebSocket closed');
    ws.close();
    setTimeout(() => startWS(app, notebookTracker), 1000);
  };

  ws.onerror = e => {
    console.log('WebSocket error');
    console.log(e);
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

  export function restartNotebook(notebookTracker: INotebookTracker) {
    if (notebookTracker.currentWidget) {
      const sessionContext = notebookTracker.currentWidget.sessionContext;
      if (sessionContext) {
        sessionContext.session?.kernel?.restart();
        console.log('Restarting kernel');
      }
    }
  }

  type Notebook = {
    metadata: {
      kernelspec: {
        display_name: string;
        language: string;
        name: string;
      };
      language_info: {
        codemirror_mode: {
          name: string;
          version: number;
        };
        file_extension: string;
        mimetype: string;
        name: string;
        nbconvert_exporter: string;
        pygments_lexer: string;
        version: string;
      };
      orig_nbformat: number;
    };
    cells: any[];
    colab: {
      provenance: [];
    };
    nbformat: number;
    nbformat_minor: number;
  };

  export async function setNotebook(
    notebookTracker: INotebookTracker,
    app: JupyterFrontEnd,
    json: string,
    test: string = 'test'
  ) {
    const notebook = JSON.parse(json) as Notebook;
    notebook.metadata.orig_nbformat = 4;
    // console.log('Setting notebook', notebook, notebook.metadata.orig_nbformat);
    // // const newJson = JSON.stringify(notebook);
    // // console.log('Setting notebook', newJson);
    // notebookTracker.currentWidget?.content.model?.fromJSON(notebook);

    // create new notebook
    // const manager = new ContentsManager();

    const notebookName = 'tensorboard.ipynb';

    // Open the notebook in JupyterLab
    const widget = await app.commands.execute('docmanager:open', {
      path: notebookName,
      factory: 'Notebook'
    });

    // set the content of the notebook to the new notebook
    notebookTracker.currentWidget?.content.model?.fromJSON(notebook);

    await app.commands.execute('docmanager:save', {});

    if (widget) {
      console.log('Notebook created and opened successfully!');
    }
  }
}
