import numpy as np
from tqdm import trange, tqdm
import tensorflow as tf

from .fedbase import BaseFedarated
from flearn.optimizer.sarah import SARAH
from flearn.optimizer.proxsarah import PROXSARAH
from flearn.utils.tf_utils import process_grad, process_sparse_grad

#WEIGHTED = False


class Server(BaseFedarated):
    def __init__(self, params, learner, dataset):
        print('Using Federated prox to Train')
        self.inner_opt = PROXSARAH(params['learning_rate'], params["lamb"])
        self.dataset = params["dataset"]
        #self.seed = 1
        super(Server, self).__init__(params, learner, dataset)

    def train(self):
        '''Train using Federated Proximal'''
        print("Train using Federated Proximal SARAH")
        print('Training with {} workers ---'.format(self.clients_per_round))

        model_len = process_grad(self.latest_model).size

        for i in range(self.num_rounds):
            # test model
            if i % self.eval_every == 0:
                stats = self.test()  # have set the latest model for all clients
                stats_train = self.train_error_and_loss()

                tqdm.write('At round {} accuracy: {}'.format(
                    i, np.sum(stats[3])*1.0/np.sum(stats[2])))  # testing accuracy
                tqdm.write('At round {} training accuracy: {}'.format(
                    i, np.sum(stats_train[3])*1.0/np.sum(stats_train[2])))
                tqdm.write('At round {} training loss: {}'.format(
                    i, np.dot(stats_train[4], stats_train[2])*1.0/np.sum(stats_train[2])))
                self.rs_glob_acc.append(np.sum(stats[3])*1.0/np.sum(stats[2]))
                self.rs_train_acc.append(
                    np.sum(stats_train[3])*1.0/np.sum(stats_train[2]))
                self.rs_train_loss.append(
                    np.dot(stats_train[4], stats_train[2])*1.0/np.sum(stats_train[2]))

                global_grads = np.zeros(model_len)
                client_grads = np.zeros(model_len)
                num_samples = []
                local_grads = []

                for c in self.clients:
                    num, client_grad = c.get_grads(model_len)
                    local_grads.append(client_grad)
                    num_samples.append(num)
                    global_grads = np.add(global_grads, client_grads * num)
                global_grads = global_grads * 1.0 / \
                    np.sum(np.asarray(num_samples))

                difference = 0
                for idx in range(len(self.clients)):
                    difference += np.sum(np.square(global_grads -
                                                   local_grads[idx]))
                difference = difference * 1.0 / len(self.clients)
                tqdm.write('gradient difference: {}'.format(difference))

            selected_clients = self.select_clients(
                i, num_clients=self.clients_per_round)

            csolns = []  # buffer for receiving client solutions

            #self.inner_opt.set_params(self.latest_model, self.client_model)

            for c in selected_clients:
                # communicate the latest model
                c.set_params(self.latest_model)
                self.inner_opt.set_wzero(self.latest_model, c.model)
                # get and set v0
                grads = c.get_raw_grads()
                c.set_vzero(grads)
                self.inner_opt.set_vzero(grads, c.model)

                # solve minimization locally
                soln, stats = c.solve_inner(self.optimizer,
                                            num_epochs=self.num_epochs, batch_size=self.batch_size)

                # gather solutions from client
                csolns.append(soln)

                # track communication cost
                self.metrics.update(rnd=i, cid=c.id, stats=stats)

            # update model
            print(self.parameters['weight'])
            self.latest_model = self.aggregate(
                csolns, weighted=self.parameters['weight'])  # Weighted = False / True
            self.client_model.set_params(self.latest_model)

        # final test model
        stats = self.test()
        stats_train = self.train_error_and_loss()

        self.metrics.accuracies.append(stats)
        self.metrics.train_accuracies.append(stats_train)
        tqdm.write('At round {} accuracy: {}'.format(
            self.num_rounds, np.sum(stats[3])*1.0/np.sum(stats[2])))
        tqdm.write('At round {} training accuracy: {}'.format(
            self.num_rounds, np.sum(stats_train[3])*1.0/np.sum(stats_train[2])))

        # save server model
        self.metrics.write()
        prox = 0
        if(self.parameters['lamb'] > 0):
            prox = 1
        self.save(prox=prox, lamb=self.parameters['lamb'],
                  learning_rate=self.parameters["learning_rate"], data_set=self.dataset, num_users=self.clients_per_round,batch = self.batch_size)

        print("Test ACC:", self.rs_glob_acc)
        print("Training ACC:", self.rs_train_acc)
        print("Training Loss:", self.rs_train_loss)
