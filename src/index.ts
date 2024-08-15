import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';

import { ISettingRegistry } from '@jupyterlab/settingregistry';

/**
 * Initialization data for the jupyter_tensorboard extension.
 */
const plugin: JupyterFrontEndPlugin<void> = {
  id: 'jupyter_tensorboard:plugin',
  description: 'A JupyterLab extension.',
  autoStart: true,
  optional: [ISettingRegistry],
  activate: (app: JupyterFrontEnd, settingRegistry: ISettingRegistry | null) => {
    console.log('JupyterLab extension jupyter_tensorboard is activated!');

    if (settingRegistry) {
      settingRegistry
        .load(plugin.id)
        .then(settings => {
          console.log('jupyter_tensorboard settings loaded:', settings.composite);
        })
        .catch(reason => {
          console.error('Failed to load settings for jupyter_tensorboard.', reason);
        });
    }
  }
};

export default plugin;
