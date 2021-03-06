# -*- coding: utf-8 -*-
# base
import os
import sys
import json
import gc
import pickle
import numpy as np
import pandas as pd
# model
import tensorflow as tf
from tensorflow import set_random_seed
from keras.backend.tensorflow_backend import set_session
from keras.preprocessing import text, sequence
from keras.callbacks import ModelCheckpoint, Callback, EarlyStopping
from keras.layers import *
from sklearn.metrics import f1_score, recall_score, precision_score
from gensim.models.keyedvectors import KeyedVectors
# my
from config import Config
from nlp.models.capsule import TextClassifier
from keras.utils.vis_utils import plot_model

# conf-my
myconf = Config("conf/capsule.conf")
vocab = [int(i) for i in myconf.label.vocab.split(',')]
with open(myconf.model.pre, 'r', encoding="UTF-8") as f:
    pre = json.load(f)
fields = myconf.data.fields.split(',')
# conf-tf
tfconf = tf.ConfigProto()
tfconf.gpu_options.allow_growth = True
set_session(tf.Session(config=tfconf))
# conf-random
np.random.seed(int(myconf.random.train_seed))
set_random_seed(int(myconf.random.train_seed))


def get_label(arr, vocab=vocab):
    arr = list(arr)
    return vocab[arr.index(max(arr))]

def get_prob(arr):
    return list(arr)


class Metrics(Callback):
    def on_train_begin(self, logs={}):
        self.val_f1s = []
        self.val_recalls = []
        self.val_precisions = []

    def on_epoch_end(self, epoch, logs={}):
        val_predict = list(map(get_label, self.model.predict(self.validation_data[0])))
        val_targ = list(map(get_label, self.validation_data[1]))
        _val_f1 = f1_score(val_targ, val_predict, average="macro")
        _val_recall = recall_score(val_targ, val_predict, average="macro")
        _val_precision = precision_score(val_targ, val_predict, average="macro")
        self.val_f1s.append(_val_f1)
        self.val_recalls.append(_val_recall)
        self.val_precisions.append(_val_precision)
        print(_val_f1, _val_precision, _val_recall)
        print("max f1")
        print(max(self.val_f1s))
        return


def train():
    model_dir = myconf.model.dir
    if not os.path.exists(model_dir):
        os.makedirs(model_dir)
    maxlen = int(myconf.model.maxlen)
    max_features = int(myconf.model.max_features)
    batch_size = int(myconf.model.batch_size)
    epochs = int(myconf.model.epochs)
    tokenizer = text.Tokenizer(num_words=None)

    train_data = pd.read_csv(myconf.data.train)
    train_data[myconf.data.src_field] = train_data.apply(lambda x: eval(x[1]), axis=1)
    val_data = pd.read_csv(myconf.data.val)
    val_data[myconf.data.src_field] = val_data.apply(lambda x: eval(x[1]), axis=1)
    if myconf.data.combine == 'yes':
        train_data = pd.concat([train_data, val_data])

    tokenizer.fit_on_texts(train_data[myconf.data.src_field].values)
    with open(myconf.model.tokenizer, 'wb') as handle:
        pickle.dump(tokenizer, handle, protocol=pickle.HIGHEST_PROTOCOL)

    word_index = tokenizer.word_index
    w2_model = KeyedVectors.load_word2vec_format(myconf.embedding.word2vec, binary=True, encoding='utf8',
                                                 unicode_errors='ignore')
    embeddings_index = {}
    embeddings_matrix = np.zeros((len(word_index) + 1, w2_model.vector_size))
    word2idx = {"_PAD": 0}
    vocab_list = [(k, w2_model.wv[k]) for k, v in w2_model.wv.vocab.items()]

    for word, i in word_index.items():
        if word in w2_model:
            embedding_vector = w2_model[word]
        else:
            embedding_vector = None
        if embedding_vector is not None:
            embeddings_matrix[i] = embedding_vector

    X_train = train_data[myconf.data.src_field].values
    Y_train = [pd.get_dummies(train_data[k])[vocab].values for k in fields]
    list_tokenized_train = tokenizer.texts_to_sequences(X_train)
    input_train = sequence.pad_sequences(list_tokenized_train, maxlen=maxlen)
    if myconf.data.combine != 'yes':
        X_val = val_data[myconf.data.src_field].values
        Y_val = [pd.get_dummies(val_data[k])[vocab].values for k in fields]
        list_tokenized_val = tokenizer.texts_to_sequences(X_val)
        input_val = sequence.pad_sequences(list_tokenized_val, maxlen=maxlen)

    for i, k in enumerate(fields):
        print('\n', k)
        model = TextClassifier().model(embeddings_matrix, maxlen, word_index, 4)
        # if i == 0:
        #     plot_model(model, to_file='capsule.png', show_shapes=True, show_layer_names=False)
        file_path = model_dir + k + "_{epoch:02d}.hdf5"
        # file_path = model_dir + k + "_{epoch:02d}-{val_loss:.2f}.hdf5"
        checkpoint = ModelCheckpoint(file_path, verbose=2, save_weights_only=True)

        # earlystop = EarlyStopping(monitor='val_f1', patience=3, restore_best_weights=True)
        # checkpoint = ModelCheckpoint(file_path, verbose=2, save_weights_only=True, save_best_only=True)
        metrics = Metrics()
        callbacks_list = [checkpoint, metrics]
        # callbacks_list = [metrics, checkpoint, earlystop]
        if myconf.data.combine == 'yes':
            history = model.fit(input_train, Y_train[i], batch_size=batch_size, epochs=epochs,
                             validation_split=0.1, callbacks=callbacks_list, verbose=2)
        else:
            history = model.fit(input_train, Y_train[i], batch_size=batch_size, epochs=epochs,
                             validation_data=(input_val, Y_val[i]), callbacks=callbacks_list, verbose=2)
        del model
        del history
        gc.collect()
        K.clear_session()


def pred():
    with open(myconf.model.tokenizer, 'rb') as handle:
        maxlen = int(myconf.model.maxlen)
        model_dir = myconf.model.dir
        tokenizer = pickle.load(handle)
        word_index = tokenizer.word_index
        test = pd.read_csv(myconf.data.test)
        test[myconf.data.src_field] = test.apply(lambda x: eval(x[1]), axis=1)
        X_test = test[myconf.data.src_field].values
        list_tokenized_test = tokenizer.texts_to_sequences(X_test)
        input_test = sequence.pad_sequences(list_tokenized_test, maxlen=maxlen)
        w2v_model = KeyedVectors.load_word2vec_format(myconf.embedding.word2vec, binary=True, encoding='utf8',
                                                     unicode_errors='ignore')
        embeddings_index = {}
        embeddings_matrix = np.zeros((len(word_index) + 1, w2v_model.vector_size))
        word2idx = {"_PAD": 0}
        vocab_list = [(k, w2v_model.wv[k]) for k, v in w2v_model.wv.vocab.items()]
        for word, i in word_index.items():
            if word in w2v_model:
                embedding_vector = w2v_model[word]
            else:
                embedding_vector = None
            if embedding_vector is not None:
                embeddings_matrix[i] = embedding_vector

        submit = pd.read_csv(myconf.data.test_download)
        submit_prob = pd.read_csv(myconf.data.test_download)

        for k, v in pre.items():
            print('\n', k)
            model = TextClassifier().model(embeddings_matrix, maxlen, word_index, 4)
            model.load_weights(os.path.join(model_dir, v))
            submit[k] = list(map(get_label, model.predict(input_test)))
            submit_prob[k] = list(map(get_prob, model.predict(input_test)))
            # submit_prob[k] = list(model.predict(input_test)) # np.array
            del model
            gc.collect()
            K.clear_session()

        submit.to_csv(myconf.data.submit, index=None)
        submit_prob.to_csv(myconf.data.submit_prob, index=None) # seg with ','


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ["-train", "-pred"]:
        raise ValueError("""usage: python run_capsule.py [-train / -pred]""")

    if sys.argv[1] == "-train":
        train()
    else:
        pred()