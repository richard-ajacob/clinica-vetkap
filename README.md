# Sistema de Agendamentos para Clínica Veterinária

Este é um aplicativo web simples desenvolvido em Python usando Flask para gerenciar agendamentos em uma clínica veterinária.

## Funcionalidades

- **Página do Cliente** (`/cliente`): Formulário para agendar consultas, vacinações, banhos e tosa, cirurgias.
- **Painel** (`/painel`): Lista de agendamentos com opção para deletar (requer login).
- Autenticação básica para acesso ao painel. Use `doutora1`, `doutora2` ou `recepcao` conforme necessário.
- Armazenamento em banco de dados SQLite.

## Como executar

1. Certifique-se de ter Python instalado.
2. Configure o ambiente virtual (já configurado).
3. Instale as dependências: `pip install flask flask-sqlalchemy`
4. Execute o aplicativo: `python app.py`
5. Abra o navegador em `http://127.0.0.1:5000/`

## Estrutura do Projeto

- `app.py`: Arquivo principal do Flask com rotas, modelo de dados e autenticação.
- `templates/cliente.html`: Página para agendamento (cliente).
- `templates/painel.html`: Página para visualizar e gerenciar agendamentos.
- `templates/login.html`: Página de login.
- `agendamentos.db`: Banco de dados SQLite (criado automaticamente).