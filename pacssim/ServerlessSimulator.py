# The main simulator for serverless computing platforms

from pacssim.SimProcess import ExpSimProcess
import numpy as np

class FunctionInstance:
    def __init__(self, t, cold_service_process, warm_service_process, expiration_threshold):
        super().__init__()

        self.cold_service_process = cold_service_process
        self.warm_service_process = warm_service_process
        self.expiration_threshold = expiration_threshold

        # life span calculations
        self.creation_time = t

        # set current state variables
        self.state = 'COLD'
        self.is_busy = True
        self.is_cold = True

        # calculate departure and expected termination on each arrival
        self.next_departure = t + self.cold_service_process.generate_trace()
        self.update_next_termination()

    def __str__(self):
        return f"State: {self.state} \t Departure: {self.next_departure:8.2f} \t Termination: {self.next_termination:8.2f}"

    def get_life_span(self):
        return self.next_termination - self.creation_time

    def update_next_termination(self):
        self.next_termination = self.next_departure + self.expiration_threshold

    def get_state(self):
        return self.state

    def arrival_transition(self, t):
        if self.state == 'COLD' or self.state == 'WARM':
            raise Exception('instance is already busy!')

        elif self.state == 'IDLE':
            self.state = 'WARM'
            self.is_busy = True
            self.next_departure = t + self.warm_service_process.generate_trace()
            self.update_next_termination()

    def is_idle(self):
        return self.state == 'IDLE'

    def make_transition(self):
        # next transition is a departure
        if self.state == 'COLD' or self.state == 'WARM':
            self.state = 'IDLE'
            self.is_busy = False
            self.is_cold = False

        # next transition is a termination
        elif self.state == 'IDLE':
            self.state = 'TERM'
            self.is_busy = False

        # if terminated
        else:
            raise Exception("Cannot make transition on terminated instance!")

        return self.state

    def get_next_transition_time(self, t=0):
        # next transition would be termination
        if self.state == 'IDLE':
            return self.get_next_termination(t)
        # next transition would be departure
        return self.get_next_departure(t)

    def get_next_departure(self, t):
        if t > self.next_departure:
            raise Exception("current time is after departure!")
        return self.next_departure - t

    def get_next_termination(self, t):
        if t > self.next_termination:
            raise Exception("current time is after termination!")
        return self.next_termination - t

class ServerlessSimulator:
    def __init__(self, arrival_process=None, warm_service_process=None, 
            cold_service_process=None, expiration_threshold=600, max_time=24*60*60, **kwargs):
        super().__init__()
        
        # setup arrival process
        self.arrival_process = arrival_process
        # if the user wants a exponentially distributed arrival process
        if 'arrival_rate' in kwargs:
            self.arrival_process = ExpSimProcess(rate=kwargs.get('arrival_rate'))
        # in the end, arrival process should be defined
        if self.arrival_process is None:
            raise Exception('Arrival process not defined!')

        # if both warm and cold service rate is provided (exponential distribution)
        # then, warm service rate should be larger than cold service rate
        if 'warm_service_rate' in kwargs and 'cold_service_rate' in kwargs:
            if kwargs.get('warm_service_rate') < kwargs.get('cold_service_rate'):
                raise Exception("Warm service rate cannot be smaller than cold service rate!")

        # setup warm service process
        self.warm_service_process = warm_service_process
        if 'warm_service_rate' in kwargs:
            self.warm_service_process = ExpSimProcess(rate=kwargs.get('warm_service_rate'))
        if self.warm_service_process is None:
            raise Exception('Warm Service process not defined!')

        # setup cold service process
        self.cold_service_process = cold_service_process
        if 'cold_service_rate' in kwargs:
            self.cold_service_process = ExpSimProcess(rate=kwargs.get('cold_service_rate'))
        if self.cold_service_process is None:
            raise Exception('Cold Service process not defined!')

        self.expiration_threshold = expiration_threshold
        self.max_time = max_time

    def reset_trace(self):
        # an archive of previous servers
        self.prev_servers = []
        self.total_req_count = 0
        self.total_cold_count = 0
        self.total_warm_count = 0
        # current state of instances
        self.servers = []
        self.server_count = 0
        self.running_count = 0
        self.idle_count = 0

    def has_server(self):
        return len(self.servers) > 0

    def __str__(self):
        return f"idle/running/total: \t {self.idle_count}/{self.running_count}/{self.server_count}"

    def req(self):
        return self.arrival_process.generate_trace()

    def cold_start_arrival(self, t):
        self.total_req_count += 1
        self.total_cold_count += 1

        self.server_count += 1
        self.running_count += 1
        new_server = FunctionInstance(t, self.cold_service_process, self.warm_service_process, self.expiration_threshold)
        self.servers.append(new_server)

    def schedule_warm_instance(self, t):
        self.total_req_count += 1
        self.total_warm_count += 1

        idle_instances = [s for s in self.servers if s.is_idle()]
        creation_times = [s.creation_time for s in idle_instances]
        
        # scheduling mechanism
        creation_times = np.array(creation_times)
        # find the newest instance
        idx = np.argmax(creation_times)
        idle_instances[idx].arrival_transition(t)

    def warm_start_arrival(self, t):
        # transition from idle to running
        self.idle_count -= 1
        self.running_count += 1
        self.schedule_warm_instance(t)

    def generate_trace(self, debug_print=False):
        # reset trace values
        self.reset_trace()

        t = 0
        next_arrival = t + self.req()
        while t < self.max_time:
            if debug_print:
                print()
                print(f"Time: {t:.2f} \t NextArrival:{next_arrival:.2f}")
                print(self)
                # print state of all servers
                [print(s) for s in self.servers]

            # if there are no servers, next transition is arrival
            if self.has_server() == False:
                t = next_arrival
                next_arrival = t + self.req()
                # no servers, so cold start
                self.cold_start_arrival(t)
                continue

            # if there are servers, next transition is the soonest one
            server_next_transitions = np.array([s.get_next_transition_time(t) for s in self.servers])

            # if next transition is arrival
            if (next_arrival - t) < server_next_transitions.min():
                t = next_arrival
                next_arrival = t + self.req()

                # if warm start
                if self.idle_count > 0:
                    self.warm_start_arrival(t)
                # if cold start
                else:
                    self.cold_start_arrival(t)
                continue

            # if next transition is a state change in one of servers
            else:
                # find the server that needs transition
                idx = server_next_transitions.argmin()
                t = t + server_next_transitions[idx]
                new_state = self.servers[idx].make_transition()
                # delete instance if it was just terminated
                if new_state == 'TERM':
                    self.prev_servers.append(self.servers[idx])
                    self.idle_count -= 1
                    self.server_count -= 1
                    del self.servers[idx]
                    if debug_print:
                        print(f"Termination for: # {idx}")
                
                # if request has done processing (exit event)
                elif new_state == 'IDLE':
                    # transition from running to idle
                    self.running_count -= 1
                    self.idle_count += 1
                else:
                    raise Exception(f"Unknown transition in states: {new_state}")




if __name__ == "__main__":
    sim = ServerlessSimulator(arrival_rate=0.3, warm_service_rate=1/2.05, cold_service_rate=1/2.2,
            expiration_threshold=600, max_time=10000)
    sim.generate_trace(debug_print=False)
  