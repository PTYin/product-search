import torch
from torch import nn
from common.loss import nce_loss


class Model(nn.Module):
    def __init__(self, word_num, item_num, embedding_size, l2):
        super(Model, self).__init__()

        self.l2 = l2
        self.word_embedding_layer = nn.Embedding(word_num, embedding_size, padding_idx=0)
        # self.log_sigmoid = nn.LogSigmoid()
        # self.word_bias = nn.Embedding(word_num, 1, padding_idx=0)
        self.item_embedding_layer = nn.Embedding(item_num, embedding_size)
        self.item_bias = nn.Embedding(item_num, 1)
        self.query_projection = nn.Linear(embedding_size, embedding_size)

        self.reset_parameters()

    def reset_parameters(self):
        nn.init.normal_(self.word_embedding_layer.weight, 0, 0.1)
        with torch.no_grad():
            self.word_embedding_layer.weight[self.word_embedding_layer.padding_idx].fill_(0)

        nn.init.zeros_(self.item_embedding_layer.weight)
        nn.init.zeros_(self.item_bias.weight)

        nn.init.xavier_normal_(self.query_projection.weight)
        nn.init.uniform_(self.query_projection.bias, 0, 0.1)

    def __fs(self, words):
        embeddings = torch.mean(self.word_embedding_layer(words), dim=1)
        embeddings = torch.tanh(self.query_projection(embeddings))
        return embeddings

    def regularization_loss(self):
        return self.l2 * (self.word_embedding_layer.weight.norm() + self.item_embedding_layer.weight.norm())

    def forward(self, items, query_words,
                mode: str,
                review_words=None,
                neg_items=None):
        """
        Parameters
        -----
        items
            (batch, )
        query_words
            (batch, word_num)
        mode
        review_words
            (batch, )
        neg_items
            (batch, k)
        """
        if mode == 'output_embedding':
            item_embeddings = self.item_embedding_layer(items)
            item_biases = self.item_bias(items).squeeze(dim=1)
            return item_embeddings, item_biases
        query_embeddings = self.__fs(query_words)

        if mode == 'test':
            return query_embeddings

        if mode == 'train':

            item_embeddings = self.item_embedding_layer(items)
            neg_item_embeddings = self.item_embedding_layer(neg_items)
            item_biases, neg_biases = self.item_bias(items).squeeze(dim=1), self.item_bias(neg_items).squeeze(dim=1)

            word_embeddings = self.__fs(review_words)
            # word_embeddings = self.__fs(query_words)

            item_word_loss = nce_loss(word_embeddings, item_embeddings, neg_item_embeddings,
                                      item_biases, neg_biases)
            regularization_loss = self.regularization_loss()
            loss = item_word_loss.mean(dim=0) + regularization_loss
            return loss
        else:
            raise NotImplementedError
