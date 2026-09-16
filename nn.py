import sqlite3 as sqlite
from math import tanh


def dtanh(y):
    # Производная функции активации tanh
    return 1.0 - y * y


class SearchNet:
    # Создание нейронной сети и подключение к базе данных
    def __init__(self, dbname):
        self.con = sqlite.connect(dbname)

    # Закрытие подключения к базе данных
    def __del__(self):
        if hasattr(self, "con"):
            self.con.close()

    # Создание таблиц, в которых хранятся скрытые узлы и веса связей
    def maketables(self):
        self.con.execute(
            "CREATE TABLE hiddennode(create_key)"
        )

        self.con.execute(
            "CREATE TABLE wordhidden(fromid,toid,strength)"
        )

        self.con.execute(
            "CREATE TABLE hiddenurl(fromid,toid,strength)"
        )

        self.con.commit()

    # Получение веса связи между двумя узлами
    def getstrength(self, fromid, toid, layer):
        # Первый слой связывает слова со скрытыми узлами
        if layer == 0:
            table = "wordhidden"
            default = -0.2

        # Второй слой связывает скрытые узлы с URL
        else:
            table = "hiddenurl"
            default = 0.0

        result = self.con.execute(
            f"""
            SELECT strength
            FROM {table}
            WHERE fromid = ? AND toid = ?
            """,
            (fromid, toid)
        ).fetchone()

        # Если связи ещё нет, возвращаем начальный вес
        if result is None:
            return default

        return result[0]

    # Изменение или создание веса связи
    def setstrength(self, fromid, toid, layer, strength):
        if layer == 0:
            table = "wordhidden"
        else:
            table = "hiddenurl"

        result = self.con.execute(
            f"""
            SELECT rowid
            FROM {table}
            WHERE fromid = ? AND toid = ?
            """,
            (fromid, toid)
        ).fetchone()

        # Если связи нет, создаём новую
        if result is None:
            self.con.execute(
                f"""
                INSERT INTO {table}
                (fromid, toid, strength)
                VALUES (?, ?, ?)
                """,
                (fromid, toid, strength)
            )

        # Если связь уже существует, изменяем её вес
        else:
            self.con.execute(
                f"""
                UPDATE {table}
                SET strength = ?
                WHERE rowid = ?
                """,
                (strength, result[0])
            )

    # Создание скрытого узла для набора слов
    def generatehiddennode(self, wordids, urls):
        # Не создаём скрытый узел для слишком большого количества слов
        if len(wordids) > 3:
            return

        # Формируем уникальный ключ из идентификаторов слов
        createkey = "_".join(
            sorted(str(wordid) for wordid in wordids)
        )

        # Проверяем, существует ли такой скрытый узел
        result = self.con.execute(
            """
            SELECT rowid
            FROM hiddennode
            WHERE create_key = ?
            """,
            (createkey,)
        ).fetchone()

        # Если узел уже существует, ничего делать не нужно
        if result is not None:
            return

        # Создаём новый скрытый узел
        cursor = self.con.execute(
            """
            INSERT INTO hiddennode(create_key)
            VALUES (?)
            """,
            (createkey,)
        )

        hiddenid = cursor.lastrowid

        # Соединяем каждое слово со скрытым узлом
        # Начальный вес распределяется между словами
        initial_weight = 1.0 / len(wordids)

        for wordid in wordids:
            self.setstrength(
                wordid,
                hiddenid,
                0,
                initial_weight
            )

        # Соединяем скрытый узел с найденными страницами
        # Начальный вес этих связей равен 0.1
        for urlid in urls:
            self.setstrength(
                hiddenid,
                urlid,
                1,
                0.1
            )

        self.con.commit()

    # Получение всех скрытых узлов,
    # связанных с указанными словами или URL
    def getallhiddenids(self, wordids, urlids):
        hiddenids = {}

        # Ищем скрытые узлы, связанные со словами запроса
        for wordid in wordids:
            rows = self.con.execute(
                """
                SELECT toid
                FROM wordhidden
                WHERE fromid = ?
                """,
                (wordid,)
            )

            for row in rows:
                hiddenids[row[0]] = 1

        # Ищем скрытые узлы, связанные с результатами поиска
        for urlid in urlids:
            rows = self.con.execute(
                """
                SELECT fromid
                FROM hiddenurl
                WHERE toid = ?
                """,
                (urlid,)
            )

            for row in rows:
                hiddenids[row[0]] = 1

        return list(hiddenids.keys())

    # Подготовка структуры нейронной сети
    def setupnetwork(self, wordids, urlids):
        self.wordids = wordids
        self.urlids = urlids

        # Получаем скрытые узлы,
        # связанные с текущим запросом и результатами
        self.hiddenids = self.getallhiddenids(
            wordids,
            urlids
        )

        # Выходы входного слоя
        self.ai = [1.0] * len(self.wordids)

        # Выходы скрытого слоя
        self.ah = [1.0] * len(self.hiddenids)

        # Выходы конечного слоя
        self.ao = [1.0] * len(self.urlids)

        # Матрица весов между словами и скрытыми узлами
        self.wi = [
            [
                self.getstrength(wordid, hiddenid, 0)
                for hiddenid in self.hiddenids
            ]
            for wordid in self.wordids
        ]

        # Матрица весов между скрытыми узлами и URL
        self.wo = [
            [
                self.getstrength(hiddenid, urlid, 1)
                for urlid in self.urlids
            ]
            for hiddenid in self.hiddenids
        ]

    # Прямое распространение сигнала по сети
    def feedforward(self):
        # Все слова запроса считаются активными
        for i in range(len(self.wordids)):
            self.ai[i] = 1.0

        # Рассчитываем значения скрытого слоя
        for j in range(len(self.hiddenids)):
            total = 0.0

            for i in range(len(self.wordids)):
                total += self.ai[i] * self.wi[i][j]

            # Функция tanh ограничивает значение диапазоном от -1 до 1
            self.ah[j] = tanh(total)

        # Рассчитываем значения выходного слоя
        for k in range(len(self.urlids)):
            total = 0.0

            for j in range(len(self.hiddenids)):
                total += self.ah[j] * self.wo[j][k]

            self.ao[k] = tanh(total)

        return self.ao[:]

    # Получение оценки URL для поискового запроса
    def getresult(self, wordids, urlids):
        self.setupnetwork(wordids, urlids)
        return self.feedforward()

    # Обратное распространение ошибки
    def backpropagate(self, targets, learning_rate=0.5):
        # Ошибки выходного слоя
        output_deltas = [0.0] * len(self.urlids)

        for k in range(len(self.urlids)):
            # Разница между желаемым и фактическим результатом
            error = targets[k] - self.ao[k]

            # Рассчитываем поправку веса
            output_deltas[k] = (
                dtanh(self.ao[k]) * error
            )

        # Ошибки скрытого слоя
        hidden_deltas = [0.0] * len(self.hiddenids)

        for j in range(len(self.hiddenids)):
            error = 0.0

            # Ошибка скрытого узла зависит от ошибок
            # всех связанных с ним выходных узлов
            for k in range(len(self.urlids)):
                error += (
                    output_deltas[k] *
                    self.wo[j][k]
                )

            hidden_deltas[j] = (
                dtanh(self.ah[j]) * error
            )

        # Изменяем веса между скрытым и выходным слоями
        for j in range(len(self.hiddenids)):
            for k in range(len(self.urlids)):
                change = (
                    output_deltas[k] *
                    self.ah[j]
                )

                self.wo[j][k] += (
                    learning_rate * change
                )

        # Изменяем веса между входным и скрытым слоями
        for i in range(len(self.wordids)):
            for j in range(len(self.hiddenids)):
                change = (
                    hidden_deltas[j] *
                    self.ai[i]
                )

                self.wi[i][j] += (
                    learning_rate * change
                )

    # Обучение сети на одном поисковом запросе
    def trainquery(self, wordids, urlids, selectedurl):
        # При необходимости создаём скрытый узел
        self.generatehiddennode(
            wordids,
            urlids
        )

        # Подготавливаем сеть
        self.setupnetwork(
            wordids,
            urlids
        )

        # Получаем текущий результат работы сети
        self.feedforward()

        # Для всех URL устанавливаем желаемый результат 0
        targets = [0.0] * len(urlids)

        # Для выбранного пользователем URL
        # устанавливаем желаемый результат 1
        targets[urlids.index(selectedurl)] = 1.0

        # Выполняем обратное распространение ошибки
        self.backpropagate(targets)

        # Сохраняем новые веса в базе данных
        self.updatedatabase()

    # Сохранение обученных весов в базе данных
    def updatedatabase(self):
        # Сохраняем веса первого слоя
        for i in range(len(self.wordids)):
            for j in range(len(self.hiddenids)):
                self.setstrength(
                    self.wordids[i],
                    self.hiddenids[j],
                    0,
                    self.wi[i][j]
                )

        # Сохраняем веса второго слоя
        for j in range(len(self.hiddenids)):
            for k in range(len(self.urlids)):
                self.setstrength(
                    self.hiddenids[j],
                    self.urlids[k],
                    1,
                    self.wo[j][k]
                )

        self.con.commit()


# Создаём объект нейронной сети
mynet = SearchNet("nn.db")