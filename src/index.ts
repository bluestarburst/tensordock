import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';

/**
 * Initialization data for the Jupyter-Tensorboard extension.
 */
const plugin: JupyterFrontEndPlugin<void> = {
  id: 'Jupyter-Tensorboard:plugin',
  description: 'A JupyterLab extension.',
  autoStart: true,
  activate: (app: JupyterFrontEnd) => {
    console.log('JupyterLab extension Jupyter-Tensorboard is activated!');
  }
};

export default plugin;
