import re
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta, timezone
from sqlalchemy import or_, inspect, text
from zoneinfo import ZoneInfo

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///agendamentos.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = 'chave_secreta_vet'  # Chave secreta para sessões
db = SQLAlchemy(app)

INTERVALO_MINUTOS = 40
PASSO_HORARIOS_MINUTOS = 40
ANTECEDENCIA_MINUTOS = 10
JANELAS_ATENDIMENTO = {
    'Bruna Prudêncio': ((8, 30), (13, 50)),
    'Karina Pereira': ((14, 0), (19, 20)),
    'Sara Thevenard': ((14, 0), (19, 20)),
}
DOUTORAS = list(JANELAS_ATENDIMENTO.keys())

try:
    APP_TIMEZONE = ZoneInfo('America/Sao_Paulo')
except Exception:
    # Fallback sem base de timezone do sistema: UTC-3 fixo (Brasilia).
    APP_TIMEZONE = timezone(timedelta(hours=-3))


def agora_local():
    # Mantemos datetime sem tzinfo para comparar com os campos salvos no banco.
    return datetime.now(APP_TIMEZONE).replace(tzinfo=None)

class Usuario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    nome = db.Column(db.String(100), nullable=False)
    senha = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(20), nullable=False)

    def __repr__(self):
        return f'<Usuario {self.username}>'

class Agendamento(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome_dono = db.Column(db.String(100), nullable=False)
    nome_pet = db.Column(db.String(100), nullable=False)
    especie = db.Column(db.String(20), nullable=False)
    sexo = db.Column(db.String(10), nullable=False)
    telefone = db.Column(db.String(20), nullable=False)
    data = db.Column(db.DateTime, nullable=False)
    servico = db.Column(db.String(200), nullable=False)
    doutora = db.Column(db.String(50), nullable=False)
    motivo = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='Agendada')
    reagendamento = db.Column(db.Boolean, nullable=False, default=False)

    def __repr__(self):
        return f'<Agendamento {self.id}>'


def gerar_horarios_disponiveis(doutora, data_consulta, agendamento_id_ignorar=None):
    janela = JANELAS_ATENDIMENTO.get(doutora)
    if not janela:
        return []

    (hora_inicio, minuto_inicio), (hora_fim, minuto_fim) = janela
    inicio_dia = datetime.combine(data_consulta, datetime.min.time()).replace(hour=hora_inicio, minute=minuto_inicio)
    fim_dia = datetime.combine(data_consulta, datetime.min.time()).replace(hour=hora_fim, minute=minuto_fim)
    agora = agora_local()
    agora_limite = agora + timedelta(minutes=ANTECEDENCIA_MINUTOS)
    duracao_consulta = timedelta(minutes=INTERVALO_MINUTOS)
    passo_horarios = timedelta(minutes=PASSO_HORARIOS_MINUTOS)

    query_agendamentos = Agendamento.query.filter(
        Agendamento.doutora == doutora,
        Agendamento.status == 'Agendada'
    )
    if agendamento_id_ignorar is not None:
        query_agendamentos = query_agendamentos.filter(Agendamento.id != agendamento_id_ignorar)

    agendamentos = query_agendamentos.all()
    agendamentos_no_dia = [a for a in agendamentos if a.data.date() == data_consulta]

    horarios = []
    horario_atual = inicio_dia

    while horario_atual + duracao_consulta <= fim_dia:
        fim_horario = horario_atual + duracao_consulta

        if data_consulta == agora.date() and horario_atual < agora_limite:
            horario_atual += passo_horarios
            continue

        conflito = False
        for agendamento in agendamentos_no_dia:
            inicio_existente = agendamento.data
            fim_existente = inicio_existente + duracao_consulta
            if horario_atual < fim_existente and fim_horario > inicio_existente:
                conflito = True
                break

        if not conflito:
            horarios.append(horario_atual.strftime('%H:%M'))

        horario_atual += passo_horarios

    return horarios

@app.route('/')
def index():
    return render_template('inicio.html', ano=datetime.now().year)


def obter_agendamento_gerenciavel(id):
    if 'logged_in' not in session:
        return None, redirect(url_for('login_page'))

    agendamento = Agendamento.query.get_or_404(id)
    role = session.get('role')
    user = session.get('user')

    if role != 'reception' and agendamento.doutora != user:
        return None, redirect(url_for('painel'))

    return agendamento, None


def existe_conflito_agendamento(doutora, inicio_consulta, duracao_consulta, agendamento_id_ignorar=None):
    fim_consulta = inicio_consulta + duracao_consulta
    query_agendamentos = Agendamento.query.filter(
        Agendamento.doutora == doutora,
        Agendamento.status == 'Agendada'
    )
    if agendamento_id_ignorar is not None:
        query_agendamentos = query_agendamentos.filter(Agendamento.id != agendamento_id_ignorar)

    for agendamento in query_agendamentos.all():
        inicio_existente = agendamento.data
        fim_existente = inicio_existente + duracao_consulta
        if inicio_consulta < fim_existente and fim_consulta > inicio_existente:
            return True

    return False

@app.route('/cliente')
def cliente():
    return render_template('cliente.html')


@app.route('/horarios-disponiveis')
def horarios_disponiveis():
    doutora = request.args.get('doutora', '').strip()
    data_str = request.args.get('data', '').strip()
    agendamento_id = request.args.get('agendamento_id', type=int)

    if not doutora or not data_str:
        return jsonify({'horarios': []})

    try:
        data_consulta = datetime.strptime(data_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'horarios': [], 'erro': 'Data inválida'}), 400

    horarios = gerar_horarios_disponiveis(doutora, data_consulta, agendamento_id_ignorar=agendamento_id)
    return jsonify({'horarios': horarios})

@app.route('/agendar', methods=['POST'])
def agendar():
    nome_dono = request.form.get('nome_dono', '').strip()
    nome_pet = request.form.get('nome_pet', '').strip()
    especie = request.form.get('especie', '').strip()
    sexo = request.form.get('sexo', '').strip()
    telefone = request.form.get('telefone', '').strip()
    data_str = request.form.get('data', '').strip()
    servico = request.form.get('servico', '').strip()
    doutora = request.form.get('doutora', 'Bruna Prudêncio').strip()
    motivo = request.form.get('motivo', '').strip()

    if not (nome_dono and nome_pet and especie and sexo and telefone and data_str and servico and doutora and motivo):
        return render_template('cliente.html', erro='Todos os campos são obrigatórios')

    telefone_pattern = re.compile(r'^\(?\d{2}\)?\s?\d{4,5}-?\d{4}$')
    if not telefone_pattern.match(telefone):
        return render_template('cliente.html', erro='Telefone inválido. Use o formato (XX) XXXXX-XXXX ou XXXXXXXXXXX.')

    # Converter string para datetime
    try:
        data = datetime.strptime(data_str, '%Y-%m-%dT%H:%M')
    except ValueError:
        return render_template('cliente.html', erro='Data ou horário inválido.')

    horarios_disponiveis_data = gerar_horarios_disponiveis(doutora, data.date())
    if data.strftime('%H:%M') not in horarios_disponiveis_data:
        return render_template('cliente.html', erro='Horário fora do período da doutora ou já indisponível. Escolha outro horário.')

    conflito = existe_conflito_agendamento(
        doutora=doutora,
        inicio_consulta=data,
        duracao_consulta=timedelta(minutes=INTERVALO_MINUTOS),
    )

    if conflito:
        return render_template('cliente.html', erro='Horário indisponível para esta doutora. Escolha outro horário.')

    novo_agendamento = Agendamento(
        nome_dono=nome_dono,
        nome_pet=nome_pet,
        especie=especie,
        sexo=sexo,
        telefone=telefone,
        data=data,
        servico=servico,
        doutora=doutora,
        motivo=motivo,
        reagendamento=False,
    )
    db.session.add(novo_agendamento)
    db.session.commit()

    session['last_agendamento_id'] = novo_agendamento.id
    return redirect(url_for('confirmacao'))

@app.route('/confirmacao')
def confirmacao():
    agendamento_id = session.pop('last_agendamento_id', None)
    if not agendamento_id:
        return redirect(url_for('index'))
    agendamento = Agendamento.query.get_or_404(agendamento_id)
    return render_template('confirmacao.html', agendamento=agendamento)


@app.route('/reagendar/<int:id>', methods=['GET'])
def reagendar_page(id):
    agendamento, resposta = obter_agendamento_gerenciavel(id)
    if resposta:
        return resposta

    return render_template(
        'reagendar.html',
        agendamento=agendamento,
        data_consulta=agendamento.data.strftime('%Y-%m-%d'),
        horario_consulta=agendamento.data.strftime('%H:%M'),
    )


@app.route('/reagendar/<int:id>', methods=['POST'])
def reagendar_salvar(id):
    agendamento, resposta = obter_agendamento_gerenciavel(id)
    if resposta:
        return resposta

    motivo = request.form.get('motivo', '').strip()
    data_str = request.form.get('data', '').strip()

    if not motivo or not data_str:
        return render_template(
            'reagendar.html',
            agendamento=agendamento,
            data_consulta=request.form.get('data_consulta', '').strip() or agendamento.data.strftime('%Y-%m-%d'),
            horario_consulta=request.form.get('horario_consulta', '').strip() or agendamento.data.strftime('%H:%M'),
            erro='Data, horário e motivo são obrigatórios.',
        )

    try:
        nova_data = datetime.strptime(data_str, '%Y-%m-%dT%H:%M')
    except ValueError:
        return render_template(
            'reagendar.html',
            agendamento=agendamento,
            data_consulta=request.form.get('data_consulta', '').strip() or agendamento.data.strftime('%Y-%m-%d'),
            horario_consulta=request.form.get('horario_consulta', '').strip() or agendamento.data.strftime('%H:%M'),
            erro='Data ou horário inválido.',
        )

    horarios_disponiveis_data = gerar_horarios_disponiveis(
        agendamento.doutora,
        nova_data.date(),
        agendamento_id_ignorar=agendamento.id,
    )
    if nova_data.strftime('%H:%M') not in horarios_disponiveis_data:
        return render_template(
            'reagendar.html',
            agendamento=agendamento,
            data_consulta=request.form.get('data_consulta', '').strip() or agendamento.data.strftime('%Y-%m-%d'),
            horario_consulta=request.form.get('horario_consulta', '').strip() or agendamento.data.strftime('%H:%M'),
            erro='Horário indisponível para esta doutora. Escolha outro horário.',
        )

    conflito = existe_conflito_agendamento(
        doutora=agendamento.doutora,
        inicio_consulta=nova_data,
        duracao_consulta=timedelta(minutes=INTERVALO_MINUTOS),
        agendamento_id_ignorar=agendamento.id,
    )
    if conflito:
        return render_template(
            'reagendar.html',
            agendamento=agendamento,
            data_consulta=request.form.get('data_consulta', '').strip() or agendamento.data.strftime('%Y-%m-%d'),
            horario_consulta=request.form.get('horario_consulta', '').strip() or agendamento.data.strftime('%H:%M'),
            erro='Horário indisponível para esta doutora. Escolha outro horário.',
        )

    novo_agendamento = Agendamento(
        nome_dono=agendamento.nome_dono,
        nome_pet=agendamento.nome_pet,
        especie=agendamento.especie,
        sexo=agendamento.sexo,
        telefone=agendamento.telefone,
        data=nova_data,
        servico=agendamento.servico,
        doutora=agendamento.doutora,
        motivo=motivo,
        status='Agendada',
        reagendamento=True,
    )

    agendamento.status = 'Concluida'

    db.session.add(novo_agendamento)
    db.session.commit()
    return redirect(url_for('painel'))

@app.route('/painel')
def painel():
    user = session.get('user')
    role = session.get('role')
    if not user:
        return redirect(url_for('login_page'))
    pagina = request.args.get('pagina', default=1, type=int)
    if not pagina or pagina < 1:
        pagina = 1

    nome_filtro = request.args.get('nome', '').strip()
    data_filtro = request.args.get('data', '').strip()
    doutora_filtro = request.args.get('doutora', '').strip()
    servico_filtro = request.args.get('servico', '').strip()
    especie_filtro = request.args.get('especie', '').strip()
    sexo_filtro = request.args.get('sexo', '').strip()
    status_filtro = request.args.get('status', '').strip()
    filtro_erro = ''

    if role == 'reception':
        base_query = Agendamento.query
        doctor_options = DOUTORAS
    else:
        base_query = Agendamento.query.filter_by(doutora=user)
        doctor_options = [user]
        doutora_filtro = user

    service_options = [
        servico for servico, in base_query.with_entities(Agendamento.servico).distinct().order_by(Agendamento.servico).all()
        if servico
    ]
    if 'Consulta' not in service_options:
        service_options.insert(0, 'Consulta')

    especie_options = ['Canino', 'Felino']
    sexo_options = ['Macho', 'Fêmea']
    status_options = ['Agendada', 'Concluida', 'Cancelada']

    query = base_query

    if nome_filtro:
        termo = f'%{nome_filtro}%'
        query = query.filter(
            or_(
                Agendamento.nome_dono.ilike(termo),
                Agendamento.nome_pet.ilike(termo)
            )
        )

    if data_filtro:
        try:
            data_inicial = datetime.strptime(data_filtro, '%Y-%m-%d')
            data_final = data_inicial + timedelta(days=1)
            query = query.filter(Agendamento.data >= data_inicial, Agendamento.data < data_final)
        except ValueError:
            filtro_erro = 'Data do filtro inválida.'

    if role == 'reception' and doutora_filtro:
        query = query.filter_by(doutora=doutora_filtro)

    if servico_filtro:
        query = query.filter_by(servico=servico_filtro)

    if especie_filtro:
        query = query.filter_by(especie=especie_filtro)

    if sexo_filtro:
        query = query.filter_by(sexo=sexo_filtro)

    if status_filtro:
        query = query.filter_by(status=status_filtro)

    metricas = {
        'total': query.count(),
        'agendada': query.filter(Agendamento.status == 'Agendada').count(),
        'concluida': query.filter(Agendamento.status == 'Concluida').count(),
        'cancelada': query.filter(Agendamento.status == 'Cancelada').count(),
    }

    paginacao = query.order_by(Agendamento.data.asc()).paginate(page=pagina, per_page=10, error_out=False)
    agendamentos = paginacao.items
    filtros = {
        'nome': nome_filtro,
        'data': data_filtro,
        'doutora': doutora_filtro,
        'servico': servico_filtro,
        'especie': especie_filtro,
        'sexo': sexo_filtro,
        'status': status_filtro,
    }
    query_params = {chave: valor for chave, valor in filtros.items() if valor}

    return render_template(
        'painel.html',
        agendamentos=agendamentos,
        paginacao=paginacao,
        doctor=user,
        role=role,
        filtros=filtros,
        query_params=query_params,
        doctor_options=doctor_options,
        service_options=service_options,
        especie_options=especie_options,
        sexo_options=sexo_options,
        status_options=status_options,
        metricas=metricas,
        filtro_erro=filtro_erro,
    )

@app.route('/veterinario')
def veterinario_alias():
    return redirect(url_for('painel'))

@app.route('/login', methods=['GET'])
def login_page():
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    username = request.form.get('username', '').strip()
    senha = request.form.get('senha', '')

    usuario = Usuario.query.filter_by(username=username).first()
    if usuario and usuario.senha == senha:
        session['user'] = usuario.nome
        session['role'] = usuario.role
        session['logged_in'] = True
        return redirect(url_for('painel'))

    return render_template('login.html', erro='Usuário ou senha incorretos')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    session.pop('user', None)
    session.pop('role', None)
    return redirect(url_for('index'))

@app.route('/deletar/<int:id>', methods=['POST'])
def deletar(id):
    agendamento, resposta = obter_agendamento_gerenciavel(id)
    if resposta:
        return resposta

    db.session.delete(agendamento)
    db.session.commit()
    return redirect(url_for('painel'))


@app.route('/concluir/<int:id>', methods=['POST'])
def concluir(id):
    agendamento, resposta = obter_agendamento_gerenciavel(id)
    if resposta:
        return resposta

    agendamento.status = 'Concluida'
    db.session.commit()
    return redirect(url_for('painel'))


@app.route('/cancelar/<int:id>', methods=['POST'])
def cancelar(id):
    agendamento, resposta = obter_agendamento_gerenciavel(id)
    if resposta:
        return resposta

    agendamento.status = 'Cancelada'
    db.session.commit()
    return redirect(url_for('painel'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()

        inspetor = inspect(db.engine)
        colunas_agendamentos = {coluna['name'] for coluna in inspetor.get_columns('agendamento')}
        if 'status' not in colunas_agendamentos:
            db.session.execute(text("ALTER TABLE agendamento ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'Agendada'"))
            db.session.commit()
        if 'reagendamento' not in colunas_agendamentos:
            db.session.execute(text("ALTER TABLE agendamento ADD COLUMN reagendamento BOOLEAN NOT NULL DEFAULT 0"))
            db.session.commit()

        Agendamento.query.filter(
            or_(Agendamento.status.is_(None), Agendamento.status == '')
        ).update({'status': 'Agendada'}, synchronize_session=False)
        db.session.commit()

        Agendamento.query.filter(Agendamento.reagendamento.is_(None)).update({'reagendamento': False}, synchronize_session=False)
        db.session.commit()

        usuarios_padrao = [
            {'username': 'bruna.prudencio', 'nome': 'Bruna Prudêncio', 'senha': 'vet456', 'role': 'doctor'},
            {'username': 'karina.pereira', 'nome': 'Karina Pereira', 'senha': 'vet789', 'role': 'doctor'},
            {'username': 'sara.thevenard', 'nome': 'Sara Thevenard', 'senha': 'vet101', 'role': 'doctor'},
            {'username': 'recepcao', 'nome': 'Recepção', 'senha': 'vetkap', 'role': 'reception'},
        ]

        mapeamento_usuarios = {
            'doutora1': {'username': 'bruna.prudencio', 'nome': 'Bruna Prudêncio'},
            'doutora3': {'username': 'karina.pereira', 'nome': 'Karina Pereira'},
            'doutora4': {'username': 'sara.thevenard', 'nome': 'Sara Thevenard'},
        }
        for antigo_username, novo_dado in mapeamento_usuarios.items():
            antigo_usuario = Usuario.query.filter_by(username=antigo_username).first()
            if not antigo_usuario:
                continue

            usuario_destino = Usuario.query.filter_by(username=novo_dado['username']).first()
            if usuario_destino:
                usuario_destino.nome = novo_dado['nome']
                db.session.delete(antigo_usuario)
            else:
                antigo_usuario.username = novo_dado['username']
                antigo_usuario.nome = novo_dado['nome']

        mapeamento_doutoras = {
            'Doutora 1': 'Bruna Prudêncio',
            'Doutora 3': 'Karina Pereira',
            'Doutora 4': 'Sara Thevenard',
        }
        for nome_antigo, nome_novo in mapeamento_doutoras.items():
            Agendamento.query.filter_by(doutora=nome_antigo).update({'doutora': nome_novo}, synchronize_session=False)

        for usuario_data in usuarios_padrao:
            usuario = Usuario.query.filter_by(username=usuario_data['username']).first()
            if usuario:
                usuario.nome = usuario_data['nome']
                usuario.senha = usuario_data['senha']
                usuario.role = usuario_data['role']
            else:
                db.session.add(Usuario(**usuario_data))

        # Remove usuários removidos da lista de doutoras
        samantha = Usuario.query.filter_by(username='samantha.neves').first()
        if samantha:
            db.session.delete(samantha)

        db.session.commit()

        # Verifica coluna doutora na tabela agendamento, adiciona se não existir
        with db.engine.connect() as conn:
            result = conn.execute(db.text("PRAGMA table_info(agendamento)"))
            columns = [row[1] for row in result]
            if 'doutora' not in columns:
                try:
                    conn.execute(db.text("ALTER TABLE agendamento ADD COLUMN doutora VARCHAR(50) DEFAULT 'Samantha Neves'"))
                    print('Coluna doutora adicionada à tabela agendamento')
                except Exception as e:
                    print('Falha ao adicionar coluna doutora:', e)
            if 'telefone' not in columns:
                try:
                    conn.execute(db.text("ALTER TABLE agendamento ADD COLUMN telefone VARCHAR(20) DEFAULT ''"))
                    print('Coluna telefone adicionada à tabela agendamento')
                except Exception as e:
                    print('Falha ao adicionar coluna telefone:', e)
            if 'especie' not in columns:
                try:
                    conn.execute(db.text("ALTER TABLE agendamento ADD COLUMN especie VARCHAR(20) DEFAULT 'Canino'"))
                    print('Coluna especie adicionada à tabela agendamento')
                except Exception as e:
                    print('Falha ao adicionar coluna especie:', e)
            if 'sexo' not in columns:
                try:
                    conn.execute(db.text("ALTER TABLE agendamento ADD COLUMN sexo VARCHAR(10) DEFAULT 'Macho'"))
                    print('Coluna sexo adicionada à tabela agendamento')
                except Exception as e:
                    print('Falha ao adicionar coluna sexo:', e)
    app.run(debug=True, host='0.0.0.0', port=5001)