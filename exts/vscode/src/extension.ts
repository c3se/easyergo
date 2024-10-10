"use strict";

import * as net from "net";
import * as path from "path";
import * as vscode from "vscode";

import { PythonExtension } from "@vscode/python-extension";
import { LanguageClient,
	 LanguageClientOptions,
	 ServerOptions,
	 State,
	 integer } from "vscode-languageclient/node";


let client: LanguageClient;
let clientStarting = false
let python: PythonExtension;
let logger: vscode.LogOutputChannel

/**
 * This is the main entry point.
 * Called when vscode first activates the extension
 */
export async function activate(context: vscode.ExtensionContext) {
    logger = vscode.window.createOutputChannel('EasyErgo', { log: true })
    logger.info("Extension activated.")

    await getPythonExtension();
    if (!python) {
        return
    }

    // Restart language server command
    context.subscriptions.push(
        vscode.commands.registerCommand("easyergo.restart", async () => {
            logger.info('restarting server...')
            await startLangServer()
        })
    )

    // Execute command... command
    context.subscriptions.push(
        vscode.commands.registerCommand("easyergo.executeCommand", async () => {
            await executeServerCommand()
        })
    )

    // Restart the language server if the user switches Python envs...
    context.subscriptions.push(
        python.environments.onDidChangeActiveEnvironmentPath(async () => {
            logger.info('python env modified, restarting server...')
            await startLangServer()
        })
    )

    // ... or if they change a relevant config option
    context.subscriptions.push(
        vscode.workspace.onDidChangeConfiguration(async (event) => {
            if (event.affectsConfiguration("pygls.server") || event.affectsConfiguration("pygls.client")) {
                logger.info('config modified, restarting server...')
                await startLangServer()
            }
        })
    )

    // Start the language server once the user opens the first text document...
    context.subscriptions.push(
        vscode.workspace.onDidOpenTextDocument(
            async () => {
                if (!client) {
                    await startLangServer()
                }
            }
        )
    )

    // // Restart the server if the user modifies it.
    // context.subscriptions.push(
    //     vscode.workspace.onDidSaveTextDocument(async (document: vscode.TextDocument) => {
    //         const expectedUri = vscode.Uri.file(path.join(getCwd(), getServerPath()))

    //         if (expectedUri.toString() === document.uri.toString()) {
    //             logger.info('server modified, restarting...')
    //             await startLangServer()
    //         }
    //     })
    // )
}

export function deactivate(): Thenable<void> {
    return stopLangServer()
}

async function startLangServer() {

    // Don't interfere if we are already in the process of launching the server.
    if (clientStarting) {
        return
    }

    clientStarting = true
    if (client) {
        await stopLangServer()
    }
    const pythonInterpreter = await getPythonInterpreter()
    const serverOptions: ServerOptions = {
        command: pythonInterpreter,
        args: ["-m", "easyergo.cli"],
    };

    client = new LanguageClient(
	'easyergo',
	serverOptions,
	getClientOptions()
    );

    const result = await client.start()

    clientStarting = false

}

async function stopLangServer(): Promise<void> {
    if (!client) {
        return
    }

    if (client.state === State.Running) {
        await client.stop()
    }

    client.dispose()
    client = undefined
}

function startDebugging(): Promise<void> {
    if (!vscode.workspace.workspaceFolders) {
        logger.error("Unable to start debugging, there is no workspace.")
        return Promise.reject("Unable to start debugging, there is no workspace.")
    }
    // TODO: Is there a more reliable way to ensure the debug adapter is ready?
    setTimeout(async () => {
        await vscode.debug.startDebugging(vscode.workspace.workspaceFolders[0], "pygls: Debug Server")
    }, 2000)
}

function getClientOptions(): LanguageClientOptions {
    const config = vscode.workspace.getConfiguration('easyergo')
    const options = {
        documentSelector: config.get<any>('documentSelector'),
        outputChannel: logger,
        connectionOptions: {
            maxRestartCount: 0 // don't restart on server failure.
        },
    };
    logger.info(`client options: ${JSON.stringify(options, undefined, 2)}`)
    return options
}

/**
 * Execute a command provided by the language server.
 */
async function executeServerCommand() {
    if (!client || client.state !== State.Running) {
        await vscode.window.showErrorMessage("There is no language server running.")
        return
    }

    const knownCommands = client.initializeResult.capabilities.executeCommandProvider?.commands
    if (!knownCommands || knownCommands.length === 0) {
        const info = client.initializeResult.serverInfo
        const name = info?.name || "Server"
        const version = info?.version || ""

        await vscode.window.showInformationMessage(`${name} ${version} does not implement any commands.`)
        return
    }

    const commandName = await vscode.window.showQuickPick(knownCommands, { canPickMany: false })
    if (!commandName) {
        return
    }
    logger.info(`executing command: '${commandName}'`)

    const result = await vscode.commands.executeCommand(commandName /* if your command accepts arguments you can pass them here */)
    logger.info(`${commandName} result: ${JSON.stringify(result, undefined, 2)}`)
}


function getServerOptions() {
    const config = vscode.workspace.getConfiguration("easyergo")
    let cwd = config.get<string>('cwd')
    let host = config.get<string>('host')
    let port = config.get<number>('port')
    let mode = config.get<string>('mode')

    return [
	"-c", cwd,
	"-h", host,
	"-p", port,
	"-m", mode
    ]
}


async function getPythonInterpreter(): Promise<string> {
    const activeEnvPath = python.environments.getActiveEnvironmentPath()
    const activeEnv = await python.environments.resolveEnvironment(activeEnvPath)
    const pythonUri = activeEnv.executable.uri

    return pythonUri.fsPath
}

async function getPythonExtension() {
    try {
        python = await PythonExtension.api();
    } catch (err) {
        logger.error(`Unable to load python extension: ${err}`)
    }
}
