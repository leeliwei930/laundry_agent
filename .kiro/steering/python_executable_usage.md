### Python version requirement
Verify the user which python version need to be use for the local project, if the project doesn't have the `.python-version` file, verify with the developer which python version that need to be use for this local project, and install it via pyenv command

### Virtual env
Before executing python command, check the project contains an initialise python virtual environment directory

If the .venv directory is found, activate the virtual environment before execute any python command

```bash
source .venv/bin/activate
```

If the .venv directory is not found, create the virtual environment and activate it
```bash
python -m venv .venv
```


